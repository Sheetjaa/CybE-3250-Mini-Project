# Freeway Drift — Python version

See [the flowcharts and code guide](HOW_IT_WORKS.md) for how the game loop,
city generation, driving, rendering, relative coordinates and recordings work.
The main chart is also available as [Mermaid source](game-flow.mmd).

Run `python game.py` for manual play or `python game.py --bot` for the basic bot.
Install dependencies with `python -m pip install -r requirements.txt`.

The default player car is a red Ferrari-inspired sports car with a low body,
dark cockpit, alloy wheels and yellow nose badge. Press **1** to select it
after switching cars. Its driving physics use the original default tuning.

Each launch generates a fresh city with connected streets, varied block sizes,
a perimeter road, downtown towers, industrial warehouses, homes, shops and parks.
The map retains its original 3,100-unit span between outer streets and the same
isometric pastel style. Press **N** for a new city, or **R** to reset the car
on the current map. **N** closes any active recording; **F9** starts a new one.
Use `python game.py --seed 8224` to revisit a particular city. The seed appears
on the HUD and in the terminal, and the generated layout is saved in recordings.

Buildings that obscure the player's car become translucent automatically and
return to full opacity when the car clears them. The effect also appears in
recorded screenshots; collision footprints and scene labels stay the same.

The Python recorder saves the complete world on every simulation frame, with
car-relative object positions and velocities. Screenshots use a separate cadence.
In observations and recordings, `car.relative_position` is `(0, 0)` and every
object's `relative_position` uses X forward and Y right from the car's center.
See [PYTHON.md](PYTHON.md) for controls, the recording schema, headless mode and
the ML policy interface in `bot.py`.

The Pygame renderer caches road scenery in a viewport-sized surface with a
128-pixel gutter, rebuilding it when the camera reaches the gutter. It sorts
only visible objects and reuses HUD text and color shading. Complete world
observations and recording labels still include off-screen objects.

To measure performance on your machine, run `python benchmark.py --frames 600`.
This includes observations, world rendering, bot decisions and physics, including
initial cache creation; it excludes the display, HUD, recording and the
interactive 60 FPS cap.
Recording speed also depends on PNG encoding and disk throughput.

The original browser implementation is preserved below for reference. Its
recorder and schema differ from the Python version.

---

## Legacy browser documentation

# Freeway Drift — driving demonstrations

Open `index.html` in a desktop browser. Choose a car and settings, click **Take a drive**, then **Record drive** in the upper-right recorder panel. In browsers that support folder access (such as desktop Chrome or Edge), the first recording click asks you to choose a save folder. Select this project's `recordings` folder; each completed drive is saved there as its own `drive-<epoch_ms>.zip` file. The browser remembers the folder only until the page is reloaded. If folder access is unavailable, the ZIP downloads to the browser's normal download location. **Save again** retries saving the same ZIP. All processing stays in the browser; no installation or account is required.

The image interval defaults to **0.2 seconds (5 images per second)** and accepts **0.1–10 seconds**. Key transitions are logged immediately, independently of screenshots; holding a key produces one press and one release, not repeated keydown rows. Only game controls are tracked. R and Escape appear as command events. Touch controls include their input source.

One second is useful for testing collection. For learning steering, try 0.1–0.2 seconds: short steering taps can fall entirely between one-second frames. This is a starting point to evaluate, not a guarantee of model quality.

## Saved files

| File | Contents |
| --- | --- |
| `frames/000000.png`, etc. | PNG game-world images resized to fit 960 × 540, in capture order. HTML controls, speedometer and the separate minimap are excluded. |
| `frames.jsonl` | One JSON object per image: filename, epoch/elapsed timestamps, image size, held keys, effective actions, car position/velocity/heading, camera, settings, and reset segment. |
| `inputs.jsonl` | One JSON object per input transition or lifecycle event, including start/stop/reset, source and synthetic releases. |
| `session.json` | Schema version, requested cadence, initial state, frame count, skipped captures, stop reason and capture errors. |

Example input row (timestamps are illustrative):

```json
{"epoch_ms":1792112707184.5,"elapsed_ms":46.5,"type":"keydown","key":"w","code":"KeyW","source":"keyboard","synthetic":false,"reason":null,"keys_held":["w"]}
```

`epoch_ms` is Unix time in **milliseconds**; divide by 1000 for epoch seconds. Each session anchors `Date.now()` to a monotonic `performance.now()` clock, so a system-clock adjustment during recording does not reorder events. These timestamps describe when the browser handles input or snapshots a rendered frame, not hardware-level keyboard timing. Use `elapsed_ms` to join records within a session. Actual capture times can differ from the requested cadence; late/overlapping capture slots are counted rather than filled with duplicate images.

Pixels and state are copied together immediately after drawing, before asynchronous PNG encoding. `keys_held` represents controls active at that frame. `actions` includes auto-acceleration and combines arrow/WASD aliases; `steering` is -1 for left, 0 for neutral and +1 for right. Position and velocity use game-world units, `car.a` is heading in radians, and `simulation_time_s` counts simulated driving time (the game caps large simulation steps, so it can differ from wall time).

## Using the data

Extract each ZIP into its own session folder. Read each `frames.jsonl` row and load its `image` path relative to that folder. For a first imitation-learning dataset, use the image as the observation and `actions` as the label. The event stream lets you reconstruct changes between frames; it cannot recover images that were never captured. Initial held keys are saved in the start state, and stop state closes the recorded interval even if a key remains physically held.

Keep auto-accelerate off when collecting fully manual demonstrations, or account for the recorded setting. Choose a consistent window size and car for the first dataset, and resize images consistently when training. Saved images fit within 960 × 540, preserve aspect ratio and are never upscaled. Every frame includes saved dimensions and original canvas dimensions (`source_width`, `source_height`). Split training and validation by whole sessions rather than adjacent frames. These demonstrations teach local driving behavior; destination-aware path planning will additionally need destinations/routes or rewards.

Pausing, changing tabs or losing window focus ends the session and saves the ZIP to the selected folder (or downloads it when folder access is unavailable). Synthetic release events clear held controls first. Resetting with R keeps recording but increments `segment`; avoid forming training sequences across segment boundaries. If saving fails, **Retry save** preserves and retries the captured recording.

Frames are buffered in memory until export. Recording automatically stops around **200 MiB of PNG data** or **2 minutes (120 seconds)**, whichever comes first; actual browser memory use is higher. At the default cadence, a full session has up to 600 images; the time limit is checked on each animation frame and exports automatically. Confirm the ZIP was saved before closing the page or starting another recording. Reloading loses any unsaved session.

## Checks

With Node.js installed, run `node --test recorder.test.cjs` from this folder. Tests exercise input-source overlap, timestamp alignment, asynchronous captures, pause/reset releases, capture failure, skipped cadence slots, export retry, the complete 600-frame two-minute boundary and image resizing. A real-browser check should additionally confirm PNG appearance and downloaded ZIP contents.


## Automatic scene labels (schema version 2)

Keep `scene-labels.js` alongside the other game files. Start driving, choose
**Look ahead (world units)** (default 140, range 10–500), and click **Record drive**.
**Show detection boxes** toggles the on-screen overlay. Green zones are clear;
red zones are blocked, and orange rectangles mark relevant obstacles. The overlay
is a separate canvas and never appears in saved PNGs.

This city has no fixed three-lane highway. The labels describe three virtual,
40-unit-wide corridors relative to the car's current heading: left, center,
and right. Distance starts at the front bumper, even when reversing. A footprint
must overlap a corridor with positive area to block it; merely touching an edge
does not count. Turning rotates the corridors with the car. These are local scene
occupancy labels, not steering commands or predictions of future collisions.

Every `frames.jsonl` row now contains `scene`:

```json
{
  "labels": {"obstacle_left": true, "obstacle_center": false, "obstacle_right": true},
  "active_labels": ["obstacle_left", "obstacle_right"]
}
```

The same `scene` object also includes `config`, `zones`, and `obstacles`. Each
obstacle has a stable ID, type, world center (`x`, `y`), heading `a` in radians,
length, width, height, car-relative center, overlapping `lanes`, and bounding boxes.
`bbox_normalized` uses `[0,1]` image fractions with named `x_min`, `y_min`,
`x_max`, `y_max` fields; `bbox_pixels` uses those fields in the saved PNG's pixel
coordinates. Both are null for objects entirely outside the image. World units
are the game's units, not calibrated meters. Car dimensions are saved in `car`.
`scene.config` is captured per frame, so changing look-ahead distance is recorded.

Obstacles include traffic (only when enabled) and buildings, the game's solid
obstacles. Trees, street furniture and the map boundary are not labeled. Building
positions use their rectangular footprint. Boxes are projected full object volumes,
clipped to the image; they are not segmentation masks or occlusion-aware visible
boxes. Labels describe game-state occupancy even if an obstacle is hidden by a
building or outside the screenshot. Images, car pose, and obstacle state are taken
from the same rendered frame before asynchronous PNG encoding.

For scene classification, use the image as input and this fixed-order float target:
`[scene.labels.obstacle_left, scene.labels.obstacle_center, scene.labels.obstacle_right]`.
Use independent sigmoid outputs with `BCEWithLogitsLoss`, since multiple labels
can be true at once. All-false means none of these three corridors is blocked.
Existing `actions`, held keys and input logs remain available. Earlier recordings
lack these new labels and need new captures or separate relabeling.
