import json
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

LABEL_NAMES = [
    "left",
    "right",
    "accelerate",
    "brake",
    "left+accelerate",
    "right+accelerate",
]
LABEL_TO_INDEX = {name: idx for idx, name in enumerate(LABEL_NAMES)}
INDEX_TO_LABEL = {idx: name for name, idx in LABEL_TO_INDEX.items()}


def normalize_key(key):
    if key is None:
        return ""
    return str(key).strip().lower()


def determine_label(row):
    """Create a single target class from the frame metadata in the JSONL record.

    The accelerate/brake classes are intentionally restricted to frames where that
    action is the only input; mixed-action states such as steering while
    accelerating are assigned to the dedicated combined labels instead.

    Frames with no meaningful driving input are intentionally excluded so the
    model is not trained on a neutral class.
    """
    keys = {normalize_key(k) for k in row.get("keys_held", [])}
    actions = row.get("actions", {})

    steering = actions.get("steering")
    left_turn = (steering is not None and int(steering) < 0) or any(k in keys for k in ["a", "arrowleft", "left"])
    right_turn = (steering is not None and int(steering) > 0) or any(k in keys for k in ["d", "arrowright", "right"])
    accelerating = any(k in keys for k in ["w", "arrowup", "up"])
    braking = any(k in keys for k in ["s", "arrowdown", "down"])

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
    """A PyTorch dataset that joins each PNG to the corresponding JSONL row."""

    def __init__(self, session_dirs, transform=None):
        self.transform = transform
        self.samples = []

        for session_dir in session_dirs:
            session_path = Path(session_dir)
            frames_jsonl = session_path / "frames.jsonl"
            if not frames_jsonl.exists():
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
                    if not image_path.exists():
                        continue

                    label = determine_label(row)
                    if label is None:
                        continue
                    self.samples.append((str(image_path), label))

        if not self.samples:
            raise ValueError(f"No image/JSON pairs were found in: {session_dirs}")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        image_path, label = self.samples[idx]
        image = Image.open(image_path).convert("RGB")
        if self.transform is not None:
            image = self.transform(image)
        return image, torch.tensor(label, dtype=torch.long)


class BetterKeyPressCNN(nn.Module):

    def __init__(self, num_classes=None):
        super().__init__()
        if num_classes is None:
            num_classes = len(LABEL_NAMES)
        self.num_classes = num_classes
        self.net = nn.Sequential(
            nn.Conv2d(3, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.Conv2d(32, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.Conv2d(64, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.Conv2d(128, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
            nn.Linear(128, 96),
            nn.ReLU(),
            nn.Dropout(0.4),
            nn.Linear(96, num_classes),
        )

    def forward(self, X):
        return self.net(X)


def make_transform(resize=(96, 96)):
    """Resize and normalize images to match the lab image-classification pipeline."""
    return transforms.Compose([
        transforms.Resize(resize),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])


def get_session_dirs(data_root=DATA_ROOT):
    return sorted([p for p in data_root.glob("drive-*") if p.is_dir()])


def build_dataloaders(batch_size=32, val_fraction=0.2):
    """Use whole-session splits, matching the project recommendation in the README."""
    session_dirs = get_session_dirs()
    if len(session_dirs) < 2:
        raise ValueError("Need at least two recordings to create train/validation splits.")

    split_index = max(1, int(len(session_dirs) * (1.0 - val_fraction)))
    train_sessions = session_dirs[:split_index]
    val_sessions = session_dirs[split_index:]

    train_dataset = DrivingKeypressDataset(train_sessions, transform=make_transform())
    val_dataset = DrivingKeypressDataset(val_sessions, transform=make_transform())

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
    return train_loader, val_loader


def compute_class_weights(loader, min_weight=0.5, max_weight=5.0):
    """Compute inverse-frequency class weights and clamp them to a safe range.

    The expanded recording set is more balanced than the original 4-session run,
    but the rarest class is still roughly 44x less common than the most common one.
    A slightly higher upper bound keeps underrepresented steering states
    informative while avoiding the extreme loss scaling that comes from raw
    inverse-frequency weights.
    """
    counts = torch.zeros(len(LABEL_NAMES), dtype=torch.float32)
    for _, y in loader:
        counts += torch.bincount(y, minlength=len(LABEL_NAMES)).float()

    inverse = torch.reciprocal(counts.clamp_min(1))
    weights = inverse / inverse.mean().clamp_min(1e-8)
    return weights.clamp(min=min_weight, max=max_weight)


def print_class_counts(loader, title="Class counts"):
    """Print the per-class distribution for a loader, including label names."""
    counts = torch.zeros(len(LABEL_NAMES), dtype=torch.long)
    total = 0
    for _, y in loader:
        batch_counts = torch.bincount(y, minlength=len(LABEL_NAMES))
        counts += batch_counts.long()
        total += y.numel()

    print(f"{title}:")
    for idx, name in enumerate(LABEL_NAMES):
        pct = (counts[idx].item() / total * 100.0) if total else 0.0
        print(f"  {name}: {counts[idx].item()} ({pct:.1f}%)")
    print(f"  total_samples: {total}")


def evaluate_model(model, loader, device):
    model.eval()
    total_loss = 0.0
    total_correct = 0
    total_seen = 0
    criterion = nn.CrossEntropyLoss()

    with torch.no_grad():
        for X, y in loader:
            X = X.to(device)
            y = y.to(device)
            logits = model(X)
            loss = criterion(logits, y)
            total_loss += loss.item() * X.size(0)
            preds = torch.argmax(logits, dim=1)
            total_correct += (preds == y).sum().item()
            total_seen += X.size(0)

    return total_loss / max(total_seen, 1), total_correct / max(total_seen, 1)


def confusion_matrix(model, loader, device):
    """Return a confusion matrix for class-wise evaluation."""
    model.eval()
    cm = torch.zeros((len(LABEL_NAMES), len(LABEL_NAMES)), dtype=torch.long)

    with torch.no_grad():
        for X, y in loader:
            X = X.to(device)
            y = y.to(device)
            preds = model(X).argmax(dim=1)
            for true_label, pred_label in zip(y.cpu().tolist(), preds.cpu().tolist()):
                cm[true_label, pred_label] += 1

    return cm


def plot_confusion_matrix(cm, labels=None, title="Confusion Matrix", save_path="confusion_matrix.png"):
    """Plot the confusion matrix as a lab-style heatmap and save it to disk."""
    labels = labels if labels is not None else LABEL_NAMES
    cm_array = np.asarray(cm)

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(cm_array, cmap="Blues")
    ax.set_title(title)
    ax.set_xlabel("Predicted label")
    ax.set_ylabel("True label")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_yticklabels(labels)

    for i in range(cm_array.shape[0]):
        for j in range(cm_array.shape[1]):
            value = cm_array[i, j]
            color = "white" if value > cm_array.max() * 0.5 else "black"
            ax.text(j, i, str(int(value)), ha="center", va="center", color=color, fontsize=9)

    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(save_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return fig, ax


def train_keypress_classifier(
    epochs=10,
    batch_size=32,
    learning_rate=1e-3,
    save_path="best_keypress_model.pt",
    min_weight=0.5,
    max_weight=5.0,
):
    train_loader, val_loader = build_dataloaders(batch_size=batch_size)
    print_class_counts(train_loader, title="Training class counts")
    print_class_counts(val_loader, title="Validation class counts")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = BetterKeyPressCNN(num_classes=len(LABEL_NAMES)).to(device)
    class_weights = compute_class_weights(train_loader, min_weight=min_weight, max_weight=max_weight).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    criterion = nn.CrossEntropyLoss(weight=class_weights)

    best_val_acc = -1.0
    best_state = None

    for epoch in range(1, epochs + 1):
        model.train()
        running_loss = 0.0
        running_correct = 0
        running_seen = 0

        for X, y in train_loader:
            X = X.to(device)
            y = y.to(device)

            optimizer.zero_grad()
            logits = model(X)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()

            running_loss += loss.item() * X.size(0)
            preds = torch.argmax(logits, dim=1)
            running_correct += (preds == y).sum().item()
            running_seen += X.size(0)

        train_loss = running_loss / max(running_seen, 1)
        train_acc = running_correct / max(running_seen, 1)
        val_loss, val_acc = evaluate_model(model, val_loader, device)

        print(
            f"Epoch {epoch}/{epochs}: "
            f"train_loss={train_loss:.4f}, train_acc={train_acc:.4f}, "
            f"val_loss={val_loss:.4f}, val_acc={val_acc:.4f}"
        )

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        cm = confusion_matrix(model, val_loader, device)
        epoch_cm_path = f"keypress_confusion_matrix_epoch_{epoch}.png"
        plot_confusion_matrix(
            cm.cpu().numpy(),
            labels=LABEL_NAMES,
            title=f"Driving Keypress Confusion Matrix (Epoch {epoch})",
            save_path=epoch_cm_path,
        )
        print(f"Saved confusion matrix for epoch {epoch} to {epoch_cm_path}")

    if best_state is not None:
        model.load_state_dict(best_state)
        torch.save({"model_state": best_state, "label_names": LABEL_NAMES}, save_path)
        print(f"Saved best model to {save_path} with validation accuracy {best_val_acc:.4f}")

    cm = confusion_matrix(model, val_loader, device)
    print("Final confusion matrix:")
    print(cm)
    plot_confusion_matrix(
        cm.cpu().numpy(),
        labels=LABEL_NAMES,
        title="Driving Keypress Confusion Matrix",
        save_path="keypress_confusion_matrix.png",
    )
    print("Saved final confusion matrix to keypress_confusion_matrix.png")
    return model, train_loader, val_loader


if __name__ == "__main__":
    print("Session folders:", [p.name for p in get_session_dirs()])
    model, train_loader, val_loader = train_keypress_classifier(epochs=10, batch_size=32, learning_rate=1e-3)

    sample_X, sample_y = next(iter(train_loader))
    print("Sample input shape:", tuple(sample_X.shape))
    print("Sample labels:", sample_y[:10].tolist())
    print("Label names:", LABEL_NAMES)
    print("First 3 labels mapped to names:", [INDEX_TO_LABEL[int(v)] for v in sample_y[:3].tolist()])
