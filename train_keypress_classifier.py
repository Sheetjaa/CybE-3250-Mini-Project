"""Train a six-class screenshot driving classifier.

Put this file beside recordings/drive-*/frames.jsonl and run:
    python train_keypress_classifier.py

Dependencies: torch, torchvision, numpy, Pillow, matplotlib.
Class weights are computed exclusively from the training split. No oversampling
is applied on top of the weighted loss. Validation uses no augmentation.
"""

import argparse
import json
import random
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

DATA_ROOT = Path(__file__).resolve().parent / "recordings"
LABEL_NAMES = ["left", "right", "accelerate", "brake",
               "left+accelerate", "right+accelerate"]
LABEL_TO_INDEX = {name: idx for idx, name in enumerate(LABEL_NAMES)}
INDEX_TO_LABEL = dict(enumerate(LABEL_NAMES))
NUM_CLASSES = len(LABEL_NAMES)
IMAGE_SIZE = (96, 96)


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    # Improves repeatability; exact reproducibility also depends on hardware
    # and software versions. Some GPU operations may still be nondeterministic.
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def normalize_key(key):
    return "" if key is None else str(key).strip().lower()


def determine_label(row):
    """Preserve the original six-class labeling policy.

    Neutral frames are excluded. Steering+brake frames retain the original
    steering label; there are no dedicated steering+brake classes.
    """
    keys = {normalize_key(k) for k in (row.get("keys_held") or [])}
    actions = row.get("actions") or {}
    steering = actions.get("steering")
    left_turn = (steering is not None and int(steering) < 0) or bool(
        keys & {"a", "arrowleft", "left"})
    right_turn = (steering is not None and int(steering) > 0) or bool(
        keys & {"d", "arrowright", "right"})
    accelerating = bool(keys & {"w", "arrowup", "up"})
    braking = bool(keys & {"s", "arrowdown", "down"})

    if left_turn and accelerating:
        return LABEL_TO_INDEX["left+accelerate"]
    if right_turn and accelerating:
        return LABEL_TO_INDEX["right+accelerate"]
    if left_turn:
        return LABEL_TO_INDEX["left"]
    if right_turn:
        return LABEL_TO_INDEX["right"]
    if accelerating and not braking:
        return LABEL_TO_INDEX["accelerate"]
    if braking and not accelerating:
        return LABEL_TO_INDEX["brake"]
    return None


class DrivingKeypressDataset(Dataset):
    def __init__(self, session_dirs, transform=None):
        self.transform = transform
        self.session_dirs = [str(Path(p).resolve()) for p in session_dirs]
        self.samples = []
        for session_dir in self.session_dirs:
            session_path = Path(session_dir)
            frames_jsonl = session_path / "frames.jsonl"
            if not frames_jsonl.exists():
                warnings.warn(f"Skipping session without frames.jsonl: {session_path}")
                continue
            with frames_jsonl.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    image_rel = row.get("image")
                    if not image_rel:
                        continue
                    image_path = session_path / image_rel
                    if not image_path.is_file():
                        continue
                    label = determine_label(row)
                    if label is not None:
                        self.samples.append((str(image_path), label))
        if not self.samples:
            raise ValueError(f"No labeled image/JSON pairs in: {session_dirs}")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        image_path, label = self.samples[idx]
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        if self.transform is not None:
            image = self.transform(image)
        return image, torch.tensor(label, dtype=torch.long)


class BetterKeyPressCNN(nn.Module):
    def __init__(self, num_classes=None):
        super().__init__()
        self.num_classes = NUM_CLASSES if num_classes is None else num_classes
        self.net = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1),
            nn.BatchNorm2d(32), nn.ReLU(),
            nn.Conv2d(32, 32, 3, padding=1),
            nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1),
            nn.BatchNorm2d(64), nn.ReLU(),
            nn.Conv2d(64, 64, 3, padding=1),
            nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1),
            nn.BatchNorm2d(128), nn.ReLU(),
            nn.Conv2d(128, 128, 3, padding=1),
            nn.BatchNorm2d(128), nn.ReLU(),
            # Preserve coarse spatial information for driving decisions.
            nn.AdaptiveAvgPool2d((3, 3)), nn.Flatten(),
            nn.Linear(128 * 3 * 3, 96), nn.ReLU(),
            nn.Dropout(0.4), nn.Linear(96, self.num_classes),
        )

    def forward(self, X):
        return self.net(X)  # Raw logits; CrossEntropyLoss handles log-softmax.


def make_transform(resize=IMAGE_SIZE, training=False):
    steps = [transforms.Resize(resize)]
    if training:
        steps.append(transforms.ColorJitter(brightness=0.10, contrast=0.10))
    # No flips: horizontal flips require swapping left/right class labels.
    steps.extend([transforms.ToTensor(),
                  transforms.Normalize((0.5,) * 3, (0.5,) * 3)])
    return transforms.Compose(steps)


def get_session_dirs(data_root=DATA_ROOT):
    return sorted(p for p in Path(data_root).glob("drive-*") if p.is_dir())


def build_dataloaders(batch_size=32, val_fraction=0.2,
                      data_root=DATA_ROOT, seed=42, num_workers=0):
    if not 0 < val_fraction < 1:
        raise ValueError("val_fraction must be between 0 and 1.")
    session_dirs = get_session_dirs(data_root)
    if len(session_dirs) < 2:
        raise ValueError("Need at least two recording sessions.")
    # Randomize whole sessions rather than splitting adjacent video frames.
    random.Random(seed).shuffle(session_dirs)
    num_val = min(len(session_dirs) - 1,
                  max(1, round(len(session_dirs) * val_fraction)))
    val_sessions = session_dirs[:num_val]
    train_sessions = session_dirs[num_val:]
    print("Training sessions:", [p.name for p in train_sessions])
    print("Validation sessions:", [p.name for p in val_sessions])

    train_dataset = DrivingKeypressDataset(
        train_sessions, make_transform(training=True))
    val_dataset = DrivingKeypressDataset(val_sessions, make_transform())
    generator = torch.Generator().manual_seed(seed)
    options = dict(batch_size=batch_size, num_workers=num_workers,
                   pin_memory=torch.cuda.is_available())
    train_loader = DataLoader(train_dataset, shuffle=True,
                              generator=generator, **options)
    val_loader = DataLoader(val_dataset, shuffle=False, **options)
    return train_loader, val_loader


def class_counts(loader):
    labels = torch.tensor([y for _, y in loader.dataset.samples], dtype=torch.long)
    return torch.bincount(labels, minlength=NUM_CLASSES)


def print_class_counts(loader, title="Class counts"):
    counts = class_counts(loader)
    total = int(counts.sum())
    print(f"\n{title}:")
    for name, count in zip(LABEL_NAMES, counts.tolist()):
        print(f"  {name:18s}: {count:5d} ({100 * count / total:6.2f}%)")
    print(f"  total_samples: {total}")


def compute_class_weights(loader):
    counts = class_counts(loader)
    missing = [LABEL_NAMES[i] for i, count in enumerate(counts.tolist())
               if count == 0]
    if missing:
        raise ValueError(
            f"Missing training classes: {missing}. Collect more sessions or "
            "change --seed to obtain a split with all training classes. "
            "Do not choose a seed based on validation accuracy.")
    # No clipping: counts[c] * weights[c] is identical for every class.
    weights = counts.sum().float() / (NUM_CLASSES * counts.float())
    print("\nTraining-only inverse-frequency weights:")
    for name, count, weight in zip(LABEL_NAMES, counts.tolist(), weights.tolist()):
        print(f"  {name:18s}: weight={weight:8.4f}, "
              f"count*weight={count * weight:.2f}")
    return weights


def metrics_from_confusion(cm):
    cm = cm.float()
    support = cm.sum(dim=1)
    predicted = cm.sum(dim=0)
    tp = cm.diag()
    recall = tp / support.clamp_min(1)
    precision = tp / predicted.clamp_min(1)
    f1 = 2 * precision * recall / (precision + recall).clamp_min(1e-12)
    present = support > 0
    return {
        "accuracy": (tp.sum() / support.sum().clamp_min(1)).item(),
        # Missing validation classes are explicitly reported, not treated as
        # evidence of good or bad recall on an unobserved class.
        "balanced_accuracy": recall[present].mean().item(),
        "macro_f1": f1[present].mean().item(),
        "recall": recall.tolist(), "precision": precision.tolist(),
        "f1": f1.tolist(), "support": support.long().tolist(),
    }


@torch.no_grad()
def evaluate_model(model, loader, device, class_weights):
    model.eval()
    cm = torch.zeros((NUM_CLASSES, NUM_CLASSES), dtype=torch.long)
    weighted_sum = unweighted_sum = weight_sum = 0.0
    total = 0
    for X, y in loader:
        X, y = X.to(device, non_blocking=True), y.to(device, non_blocking=True)
        logits = model(X)
        per_sample_loss = nn.functional.cross_entropy(logits, y, reduction="none")
        sample_weights = class_weights[y]
        weighted_sum += (per_sample_loss * sample_weights).sum().item()
        weight_sum += sample_weights.sum().item()
        unweighted_sum += per_sample_loss.sum().item()
        total += y.numel()
        flat = (y * NUM_CLASSES + logits.argmax(dim=1)).cpu()
        cm += torch.bincount(flat, minlength=NUM_CLASSES ** 2).reshape(
            NUM_CLASSES, NUM_CLASSES)
    result = metrics_from_confusion(cm)
    result["weighted_loss"] = weighted_sum / max(weight_sum, 1e-12)
    result["unweighted_loss"] = unweighted_sum / max(total, 1)
    return result, cm


def plot_confusion_matrix(cm, labels=None, title="Confusion Matrix",
                          save_path="confusion_matrix.png", normalize=False):
    labels = LABEL_NAMES if labels is None else labels
    values = np.asarray(cm, dtype=float)
    if normalize:
        values = values / np.maximum(values.sum(axis=1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(9, 7))
    im = ax.imshow(values, cmap="Blues", vmin=0,
                   vmax=1 if normalize else None)
    ax.set(title=title, xlabel="Predicted label", ylabel="True label")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_yticklabels(labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            value = values[i, j]
            label = f"{value:.1%}" if normalize else str(int(value))
            ax.text(j, i, label, ha="center", va="center", fontsize=9,
                    color="white" if value > values.max() * 0.5 else "black")
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(save_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def train_keypress_classifier(
    epochs=50, batch_size=32, learning_rate=1e-3,
    save_path="best_keypress_model.pt", data_root=DATA_ROOT,
    val_fraction=0.2, seed=42, num_workers=0, patience=10,
    weight_decay=1e-4,
):
    if epochs < 1 or patience < 1:
        raise ValueError("epochs and patience must be positive.")
    seed_everything(seed)
    train_loader, val_loader = build_dataloaders(
        batch_size, val_fraction, data_root, seed, num_workers)
    print_class_counts(train_loader, "Training class counts")
    print_class_counts(val_loader, "Validation class counts")
    missing_val = [LABEL_NAMES[i] for i, n in
                   enumerate(class_counts(val_loader).tolist()) if n == 0]
    if missing_val:
        warnings.warn(f"Validation is missing {missing_val}. Balanced accuracy "
                      "covers only classes present; obtain broader validation "
                      "recordings to assess all six classes.")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Device:", device)
    model = BetterKeyPressCNN().to(device)
    weights = compute_class_weights(train_loader).to(device)
    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate,
                                  weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=3,
        threshold=1e-4, threshold_mode="abs", min_lr=1e-6)
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    best_score, best_loss = -1.0, float("inf")
    best_state, best_epoch = None, 0
    stale_epochs = 0
    history = []

    for epoch in range(1, epochs + 1):
        model.train()
        loss_sum = weight_sum = 0.0
        correct = seen = 0
        for X, y in train_loader:
            X, y = X.to(device, non_blocking=True), y.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            logits = model(X)
            loss = criterion(logits, y)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
            optimizer.step()
            # Weighted CE means divide by the sum of target weights, not
            # the batch size. Use that denominator for epoch reporting too.
            batch_weight = weights[y].sum().item()
            loss_sum += loss.item() * batch_weight
            weight_sum += batch_weight
            correct += (logits.argmax(1) == y).sum().item()
            seen += y.numel()

        val, cm = evaluate_model(model, val_loader, device, weights)
        score = val["balanced_accuracy"]
        scheduler.step(score)
        entry = {"epoch": epoch, "train_weighted_loss": loss_sum / weight_sum,
                 "train_accuracy": correct / seen, "validation": val,
                 "learning_rate": optimizer.param_groups[0]["lr"]}
        history.append(entry)
        print(f"Epoch {epoch:02d}/{epochs}: "
              f"train_loss={entry['train_weighted_loss']:.4f}, "
              f"train_acc={entry['train_accuracy']:.3f}, "
              f"val_loss={val['weighted_loss']:.4f}, "
              f"val_acc={val['accuracy']:.3f}, "
              f"val_bal_acc={score:.3f}, val_macro_f1={val['macro_f1']:.3f}, "
              f"lr={entry['learning_rate']:.2g}")

        improved = (score > best_score + 1e-4 or
                    (abs(score - best_score) <= 1e-4 and
                     val["weighted_loss"] < best_loss - 1e-4))
        if improved:
            best_score, best_loss = score, val["weighted_loss"]
            best_epoch, stale_epochs = epoch, 0
            best_state = {k: v.detach().cpu().clone()
                          for k, v in model.state_dict().items()}
            # Save immediately so an interrupted run retains its best model.
            torch.save({
                "model_state": best_state, "label_names": LABEL_NAMES,
                "architecture": "BetterKeyPressCNN_spatial_3x3",
                "class_weights": weights.detach().cpu(),
                "image_size": list(IMAGE_SIZE),
                "normalization_mean": [0.5] * 3,
                "normalization_std": [0.5] * 3,
                "epoch": epoch, "validation_metrics": val,
                "seed": seed,
                "train_sessions": train_loader.dataset.session_dirs,
                "validation_sessions": val_loader.dataset.session_dirs,
                "training_config": {
                    "batch_size": batch_size, "learning_rate": learning_rate,
                    "weight_decay": weight_decay, "val_fraction": val_fraction,
                    "max_epochs": epochs, "patience": patience,
                },
            }, save_path)
            plot_confusion_matrix(cm.numpy(), save_path=save_path.with_name(
                save_path.stem + "_confusion_counts.png"))
        else:
            stale_epochs += 1
        if stale_epochs >= patience:
            print(f"Early stopping after {patience} epochs without improvement.")
            break

    model.load_state_dict(best_state)
    val, cm = evaluate_model(model, val_loader, device, weights)
    print(f"\nBest epoch: {best_epoch}; balanced accuracy: "
          f"{val['balanced_accuracy']:.3f}; overall accuracy: {val['accuracy']:.3f}")
    print("\nClass                 Support  Precision  Recall   F1")
    for i, name in enumerate(LABEL_NAMES):
        if val["support"][i] == 0:
            print(f"{name:21s} {0:6d}       N/A     N/A    N/A")
        else:
            print(f"{name:21s} {val['support'][i]:6d} "
                  f"{val['precision'][i]:10.3f} {val['recall'][i]:7.3f} "
                  f"{val['f1'][i]:6.3f}")
    plot_confusion_matrix(cm.numpy(), normalize=True,
                          title="Best Model: Recall by True Class",
                          save_path=save_path.with_name(
                              save_path.stem + "_confusion_normalized.png"))
    save_path.with_name(save_path.stem + "_history.json").write_text(
        json.dumps(history, indent=2), encoding="utf-8")
    print(f"Saved best model: {save_path}")
    return model, train_loader, val_loader


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--save-path", type=Path, default=Path("best_keypress_model.pt"))
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--val-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    args = parser.parse_args()
    train_keypress_classifier(**vars(args))
