# Freeway Drift in Python

The native Python version runs with Pygame. Simulation, rendering, recording,
and policy code live in separate files. The original JavaScript/HTML version is
preserved as a legacy version; opening `index.html` still launches that version.
Python is a desktop application, not Python executed inside the browser.

## Run

From this directory, with Python 3.10 or newer:

```sh
python -m pip install -r requirements.txt
python game.py
python game.py --bot
```

The repository's existing `.venv` already has Pygame available. From the repository root:

```sh
.venv/bin/python CybE-3250-Mini-Project/Freeway-Drift/game.py --bot
```

| Key | Action |
| --- | --- |
| WASD / arrows | Accelerate, brake/reverse, steer |
| Space | Handbrake |
| R | Reset player; increment recording segment |
| N | Generate a new city; close the active recording |
| Escape | Pause/resume; pausing closes the active recording |
| B | Switch between manual and bot control |
| F9 | Start/stop recording |
| T | Toggle traffic |
| G | Toggle local occupancy zones |
| 1 / 2 / 3 | Select Ferrari / Weekender / Explorer |

When the bot is enabled, it keeps driving and recording after you switch to
another window or minimize the game. Manual driving still pauses and closes
recording on focus loss. Held keyboard controls are cleared in both modes.
Escape explicitly pauses either mode.
The window includes an isometric city, three car physics profiles, traffic,
building/boundary collisions, skid/impact effects, HUD and minimap. Browser touch
controls, folder picker and engine audio are retained only in the legacy version.
The Python city uses a procedural street network with varied spacing, side
streets, a perimeter ring and downtown, industrial, residential, commercial and
park districts. All intersections are connected. The map size, pastel palette,
isometric projection and fixed simulation steps are preserved. Traffic follows
continuous central avenues; the demonstration bot keeps its central loop.
It is not a byte-for-byte replay engine for old browser sessions.

The CLI chooses a random city seed on each launch. Use `--seed 8224` (or the seed
shown on the HUD) to reproduce a layout. `World()` remains deterministic by
default for Python training code. R keeps the map; N replaces it and closes any
active recording. Press F9 to begin a session in the new city.

## Recording every world frame

```sh
python game.py --record
python game.py --bot --record --image-interval 0
```

Each session streams into its own `recordings/drive-.../` directory:

| File | Contents |
| --- | --- |
| `frames.jsonl.gz` | **Every simulated frame**, at 60 simulation frames/s, with complete world context and chosen actions |
| `frames/*.png` | Optional world images, fitting 960 x 540; excludes HUD, minimap and detection overlay |
| `inputs.jsonl` | Input transitions, controller/settings changes, reset and lifecycle events |
| `session.json` | Schema 3 metadata, initial/final state, counts and completion status |

PNG interval defaults to 0.2 simulated seconds; `--image-interval 0` saves every
frame. Frames without a screenshot have `image: null` and still contain the
entire world. Recording stops after 120 simulated seconds by default;
`--max-record-seconds 0` removes that limit. F9 starts another session. Recording
data is streamed with fast gzip compression rather than accumulated in RAM or
assembled into a ZIP. Disk use still grows with recording duration. Full-world state logs are large;
plan for hundreds of MiB per minute, plus PNGs, depending on the scene.

Each row includes `frame`, `record_frame`, `simulation_time_s`, monotonic
`elapsed_ms`, anchored Unix `epoch_ms`, `segment`, `keys_held`, `controller`,
`actions`, `car`, `camera`, `settings`, `rng_state`, `collisions`, `scene`, and
`world`. Wall time and simulation time are separate: interactive play advances
one fixed step per loop, so under load the game slows instead of dropping state
frames. Headless play runs as fast as possible.

`world.objects` includes **every** building, tree, lamp, bench, traffic vehicle,
fountain, particle and skid, including objects behind the car or outside the
image. Disabled traffic remains present with `active: false` and zero velocity.
Road layout, park geometry and world bounds are included separately in `world`.
`world.city` contains the generator version and seed, street coordinates, actual
road rectangles with intersection endpoints, blocks and district centers.
`world.roads.segments_field` points to `city.roads`; the old regular-grid
`indices` field is replaced by this generated network. Terrain grip, drawing
and the minimap all use the same road rectangles.
Objects use stable IDs, world center coordinates, dimensions, heading, world
velocity, `solid`, `active`, and:

- `relative_position.x/y`: car-relative position, with X forward and Y right.
- `relative_center.forward/right`: center relative to the controlled car.
- `relative_velocity.forward/right`: object velocity minus player velocity,
  rotated into the player's axes; this is not a rotating-frame time derivative.
- `relative_heading`: wrapped heading difference in radians.
- `distance`: Euclidean center distance in world units.
- `lanes`: positive-area overlap with left/center/right lookahead corridors.

The player's `car.relative_position` is always `{"x": 0.0, "y": 0.0}`;
`car.relative_heading` is zero. Every object, including every building and
traffic car, has `relative_position` in that same frame. For example,
`{"x": 100, "y": -20}` means 100 units ahead and 20 units to the left.
These positions update when the car moves or turns. `relative_center` retains
the same values under the names `forward` and `right` for existing policies.
Use `relative_heading` for an object's orientation relative to the car.
The ordinary `x`, `y`, and `a` fields retain world positions and headings for
rendering, map reconstruction and replay. Recorded initial/final states and
every frame include the new fields; existing recordings are unchanged.

Footprint corners can be reconstructed from the center, heading and dimensions
with `scene_labels.corners`; redundant corner coordinates are omitted from logs.
Forward follows the car heading; positive right is clockwise in the game's
screen-down world coordinates. These units are not calibrated meters. Buildings
and active traffic are solid; trees and furniture are decorative, matching the
original gameplay. Boundaries are collision constraints in `world.bounds`.
Traffic velocities describe the current lane motion, zero when blocked; wrapping
a traffic car at the map edge is a teleport. Skids also have a relative endpoint.
Particles include height, lifetime and velocity; skids include lifetime.

`scene.labels` keeps the three independent obstacle occupancy labels, with
`scene.zones` and `scene.config`. Use `--lookahead 200` to change detection distance
(10–500). This distance limits occupancy zones, **not** world recording.
When rendering, objects also include clipped `bbox_normalized` image boxes;
PNG-bearing rows include `bbox_pixels` in saved image coordinates. Boxes describe
approximate full volumes and are not occlusion-aware. State-only headless runs
have no image boxes or viewport. Frame state and pixels are captured together
before stepping the simulation. A normal exit finalizes streams and metadata;
force-killing the process can leave the final gzip block incomplete.

## Bot and future ML policy

For background play, use `python game.py --bot` and switch to another window.
For a bot with no game window, run:

```sh
python game.py --background
python game.py --background --record --render
```

`--background` enables the bot automatically, runs at up to 60 simulation frames
per second and continues until you stop it with Ctrl+C. `--render` lets it save
screenshots without opening a window; without it recordings contain state only.
The terminal process must remain running. On Linux, you can also launch it as a
shell background job from this directory:

```sh
python game.py --background > /tmp/freeway-drift.log 2>&1 &
bot_pid=$!
# Stop the bot and finalize any recording:
kill "$bot_pid"
```

Ctrl+C and SIGTERM finalize active recordings. The usual 120 simulated second
recording limit still applies; use `--max-record-seconds 0` for unlimited recording.
Use `--steps 3600` for a finite background run; `--steps 0` means no frame limit.
The separate `--headless --bot` mode runs as fast as possible and defaults to
3600 frames, which is useful for bounded training runs.

`bot.py` defines `Policy.act(observation) -> simulation.Action` and a `BasicBot`.
The bot follows a clockwise road loop using heading control and slows for nearby
solid objects. Its target speeds are 120 world units/s on straights (about
58 km/h on the HUD) and 45 in turns. Adjust `BasicBot.CRUISE_SPEED` and
`BasicBot.TURN_SPEED` in `bot.py` to tune these targets; obstacle braking can
lower them. It is a basic driving example, may wait behind traffic, and does
not plan arbitrary routes or recover from every off-road position. R resets it.

The observation is exactly the dictionary recorded in a frame. An action is:

```python
from simulation import Action

class ModelPolicy:
    def act(self, observation):
        # Insert preprocessing and model inference here.
        return Action(accelerate=True, brake_reverse=False,
                      steering=0.0, handbrake=False)
```

Put that class in `model_policy.py`, then run:

```sh
python game.py --bot --policy model_policy:ModelPolicy
```

Load weights once in the policy constructor. Steering accepts floats in [-1, 1];
the other controls are booleans. A policy sees the complete state, including
objects invisible to a camera, so select input features deliberately. For a
pixel-input model, add image preprocessing to the policy interface; the current
policy contract is state-based.

**Action alignment:** frame N is the observation **before** its recorded action
is applied. That action advances the simulation to frame N+1. This makes rows
direct observation/action pairs for imitation learning. Do not join sequences
across resets, controller switches, or session boundaries. New recordings use
schema 3 and differ from the legacy browser's schema 2.

Read data with the standard library:

```python
import gzip, json
from pathlib import Path

session = Path('recordings/drive-...')
with gzip.open(session / 'frames.jsonl.gz', 'rt') as stream:
    for line in stream:
        frame = json.loads(line)
        objects = frame['world']['objects']
        target = frame['actions']
        image_path = session / frame['image'] if frame['image'] else None
```

Simulation-only training needs no Pygame import:

```python
from simulation import World
from bot import BasicBot

world, policy = World(seed=8224), BasicBot()
for _ in range(600):
    observation = world.observe()
    world.step(policy.act(observation))
```

Headless CLI examples:

```sh
python game.py --headless --bot --steps 3600 --record
python game.py --headless --bot --steps 60 --render --record --image-interval 0
python -m unittest -v test_python.py
```

The first command saves state without images and needs only the standard library.
The second uses Pygame's dummy display driver and saves images. Tests cover
repeatability, whole-world inclusion, coordinate transforms, exact zone overlap,
collisions/reset, control validation, bot traversal, recording/action alignment,
duration limits, and synchronized PNG capture.
