# Policy link: LeRobot to ROS through rosbridge

How the learned policy reads the hand and the camera and moves the fingers.
Status: adapter implemented, smoke check passed against rosbridge on one machine. Date: 2026-09-19. This closes open question 1
of `../system-design.md`.

## Decisions

- All LeRobot parts run on the GPU laptop: `policy_server`, `RobotClient`,
  `lerobot-record` and our `ExoHand` adapter. The wearable ROS machine gets no
  new code, no `lerobot` and no torch.
- The adapter reaches ROS through the rosbridge WebSocket
  (`ws://<wearable-ip>:9090`) with `roslibpy`. Both launch files start
  rosbridge already, and `application/backend` uses the same path. No process
  imports both `rclpy` and `lerobot`.
- Link loss: the hand holds. The HAL keeps the last target with no time limit,
  so this is the present behaviour. There is no HAL watchdog. An open on
  timeout drops the object at each WiFi dropout.
- The adapter obeys the `/hand/command` rule of `physical_layer/CLAUDE.md`
  (publish only when there is something new): it has a deadband of `0.01`.
- The code goes in a new top-level folder, `policy/`.
- The `htn_auto` package is removed. It has no function in this layout.

## Scope

In: the `ExoHand` adapter with RGB and the finger state, its tests, a smoke
check against the sim, the removal of `htn_auto`, the CLAUDE.md updates.

Out:
- Depth. The first training version is RGB only. Depth needs a fixed 16-bit to
  8-bit conversion (LeRobot cameras are `H x W x 3` uint8) that is identical
  in recording and inference; `application/backend/app/depth.py` has the
  `compressedDepth` decode.
- Command arbitration (open question 7 of `../system-design.md`).
- The data collection method, the release signal, training.
- The emergency open and the force limit of `../system-design.md` (Safety).

## Data flow

```
wearable ROS machine                          GPU laptop
  HAL --/hand/state--------+
  camera --.../compressed--+--> rosbridge ==ws:9090==> ExoHand <-- RobotClient
  HAL <--/hand/command-----+                                          | gRPC, localhost
                                                                policy_server
```

- rosbridge pushes each message when it is published. The adapter keeps only
  the latest one. `get_observation()` reads the stored values and does not
  wait for the network.
- Each camera frame crosses WiFi (~30-50 KB JPEG at 15 fps, ~0.5-0.75 MB/s),
  also the frames that the policy does not use. If this is too much, set
  `throttle_rate` on the subscription; rosbridge then drops frames on the ROS
  machine.
- The action queue of `RobotClient` is on the GPU laptop. Each command crosses
  WiFi. A dropout stops the commands immediately; the queue does not drain
  into the hand.

## Components

### `policy/` - the adapter package

Plain Python (>= 3.12, a requirement of `lerobot`), outside the colcon build.
Dependencies: `lerobot` 0.6.1, `roslibpy`, `opencv-python`, `numpy`.

`lerobot` finds a third-party robot only as an installed distribution with a
name that starts with `lerobot_robot_`, and it looks for the class with the
name of the config class without `Config`. Thus:

```
policy/
  pyproject.toml                  distribution lerobot_robot_exo_hand
  lerobot_robot_exo_hand/
    __init__.py                   imports the two classes (registration)
    config_exo_hand.py            ExoHandConfig, registered as "exo_hand"
    exo_hand.py                   ExoHand
    convert.py                    pure functions, no lerobot import
  tests/
```

`ExoHandConfig` (a LeRobot `RobotConfig`):

| Field | Default | |
|---|---|---|
| `host` | - | IP of the wearable machine |
| `port` | `9090` | |
| `color_topic` | `/camera/color/image_raw/compressed` | never `image_raw`: rosbridge sends it as base64 JSON |
| `max_age_s` | `0.3` | oldest state or frame that `get_observation()` accepts |
| `command_tolerance` | `0.01` | deadband of `send_action()` |

`ExoHand` (a LeRobot `Robot`):

- Features: `thumb.pos`, `index.pos`, `middle.pos`, `ring.pos`, `pinky.pos`
  (float, `0` = open .. `1` = closed, the values of the topics with no
  conversion) for observation and action, and two cameras (`H x W x 3`, uint8,
  RGB): `camera1`, the head iPhone (`head_topic`; empty = wrist only, for the old
  datasets and a bench with no phone; `iphone-camera-design.md`), and `camera2`,
  the wrist RealSense. These are image slots of `smolvla_base`, so no
  `rename_map` is necessary in recording, training or inference.
- `connect()`: opens `roslibpy.Ros`, subscribes to `/hand/state`, the color
  topic, the head topic and `/hand/command` with `queue_length=1` and no throttle, advertises
  `/hand/command` on a second `Topic` object (a `Topic` replays only one of
  subscribe / advertise after a reconnect, see `ros_client.py`), and waits
  until the first state and frame arrive or a timeout expires.
- Callbacks run on the `roslibpy` reactor thread. They store the latest
  message and its arrival time (`time.monotonic()`) under one lock. The JPEG
  stays encoded there.
- `get_observation()`: raises `ConnectionError` if the state or the frame is
  missing or older than `max_age_s`. Otherwise it decodes the JPEG, converts
  BGR to RGB and returns the flat dict. Without the age check, a lost link
  gives the last frame again with no error.
- `send_action(action)`: clamps to `0..1`. It publishes the 5 values only if
  one of them differs by more than `command_tolerance` from the last command
  seen on the topic (from us or from another publisher). It returns the
  command that the HAL has after the call: the new one, or the last one seen
  when nothing was published. A slow drift is not lost, because the comparison
  is against the last command on the topic and not against the last action.
- `calibrate()` and `configure()` do nothing: calibration is in the HAL.
- Timestamps are arrival times on the GPU laptop, not ROS stamps. This is
  sufficient at 15 fps.

The pure parts are module functions, so the tests need no rosbridge:
`decode_color`, `to_observation`, `to_command`, `differs`, `is_fresh`.

The rosbridge code is not shared with `application/backend/app/ros_client.py`.
That class is tied to the `Hub` and throttles for a browser; the common part
is ~15 lines, and `policy/` must not import from `application/`.

### Removal of `htn_auto`

Delete `physical_layer/ros2_ws/src/htn_auto/` and its `exec_depend` in
`htn_launch/package.xml`, and its line in the root `README.md`. No launch file
starts it.

### CLAUDE.md updates

- Root: the planned folder becomes `policy/`; remove "`htn_auto` in the ROS
  workspace is the thin bridge".
- `physical_layer/CLAUDE.md`: remove the `htn_auto` entries; in the
  `/hand/command` rule, replace "later `htn_auto`" with the policy adapter
  through rosbridge. Pull first: origin changed this file.

## Behaviour with other publishers

- The last message on `/hand/command` wins. A policy that moves the hand
  publishes at 15-30 Hz and overrides teleop and the web console. The takeover
  is to stop the client. Anything better is arbitration (out of scope).
- A policy that holds a pose publishes nothing, because of the deadband. Other
  publishers can move the hand during that time, and the policy sees the
  result in `/hand/state`.
- The control window follows the policy commands on its sliders. This is the
  live view of the policy output.
- If teleop drives the hand during `lerobot-record`, the adapter does not echo
  the command: it is inside the deadband of the command that teleop published.

## Failure behaviour

| Event | Result |
|---|---|
| WiFi drops | No new commands. The hand finishes the last commanded move and holds. `get_observation()` raises after `max_age_s`; the client stops. `roslibpy` reconnects by itself, the client restart is manual. |
| Camera stops, HAL runs | Same: the frame is old, the client stops, the hand holds. |
| `policy_server` slow or down | The queue of `RobotClient` runs empty, no commands, the hand holds. |
| Other device on the network publishes `/hand/command` | The HAL obeys it. rosbridge has no authentication: use an own router, a hotspot or a cable. |

## Tests

`policy/test_exo_hand.py`, plain `pytest`, no rosbridge and no `lerobot`
import where possible:

- `to_command` clamps, keeps the finger order, rejects a missing finger.
- `differs` with values inside, at and outside the tolerance; a drift of many
  small steps publishes at some point.
- `is_fresh` with a missing value, an old state, an old frame.
- `decode_color` gives RGB: a JPEG of a pure red image has its red channel
  first.
- `to_observation` has exactly the keys of `observation_features`.

Smoke check: `python -m lerobot_robot_exo_hand.exo_hand --host <ip>` against
`sim.launch.py`, after `pip install -e policy`.
It prints the observation keys, shapes and ages, closes and opens the hand one
time, and fails if `/hand/state` does not follow.

## Implementation order

1. Done: `lerobot` 0.6.1, checked against its source. `Robot` needs
   `observation_features`, `action_features`, `is_connected`,
   `connect(calibrate=True)`, `is_calibrated`, `calibrate`, `configure`,
   `get_observation`, `send_action`, `disconnect`. `RobotClient` has
   `actions_per_chunk`, `chunk_size_threshold` (default 0.5) and
   `aggregate_fn_name`.
2. Done: pure functions and their tests (`convert.py`).
3. `ExoHand` is done, with tests that feed its callbacks directly (no
   rosbridge). The smoke check,
   `python -m lerobot_robot_exo_hand.exo_hand --host <ip>`, passed on
   2026-09-19 on one machine: the HAL node alone with the sim backend (no
   Gazebo, so `/hand/state` is the rate-limited command), rosbridge, and a
   temporary node that published one JPEG at 15 Hz. Not done: from a second
   device (firewall, TCP 9090), and with a real camera. The sim has no
   simulated camera, so `connect()` fails with a RealSense unplugged.
4. Full loop: `policy_server` and `RobotClient` with `smolvla_base` (the
   actions have no meaning, the loop and the timing are the test). Measure the
   frame age and the command rate. The commands are in
   `policy/README.md`, checked against the 0.6.1 source, not run.
5. Done: `htn_auto` removed, the CLAUDE.md files and the README updated.

## The camera key

In lerobot 0.6.1, `RobotClient` does not pass a `rename_map`, and
`policy_server` overrides the map of the checkpoint with that empty map. It
then looks up `observation.images.<camera key of the robot>` in the image
features of the policy; a key that the policy does not have is a `KeyError`.
A `rename_map` works in training and in `lerobot-record`, but not in async
inference. The adapter thus uses the policy keys directly (`CAMERA` and
`HEAD_CAMERA` in `convert.py`). The keys are in the dataset: a change after the
first recording needs a dataset conversion, and datasets recorded with one
camera do not mix with datasets of two.

## Not verified

- rosbridge binds all interfaces by default (the launch files set only
  `port`). Not tested from a second device.
- CPU load of rosbridge base64 on a Pi with two image clients (web console and
  policy).
- Effect of the `0.01` deadband on the task. It is 1% of the finger range; the
  expected effect is none.
