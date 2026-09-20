# application/ - web simulator

A web console for the exoskeleton hand: a three.js viewport of the hand moving
live, plus two camera panels - the RealSense, switchable between its RGB image
and its colorized depth image, and the iPhone head camera (colour only). It is a pure
consumer of the ROS topics in `physical_layer/`; it works identically whether
the hand is simulated (`sim.launch.py`) or real (`hardware.launch.py`).

```
physical_layer (ROS 2)  --rosbridge ws://localhost:9090-->  backend (FastAPI :8000)  --ws/http-->  frontend (Next.js :3000)
```

- `backend/`  - FastAPI + `roslibpy`. The only thing that talks to ROS.
- `frontend/` - Next.js (App Router, TypeScript), Tailwind, shadcn/ui, framer-motion (`motion`), three.js via `@react-three/fiber` + `drei`, `urdf-loader`.

The browser never talks to rosbridge directly. The iPhone is a ROS camera (`iphone_camera_node` in
`physical_layer/`, `docs/specs/iphone-camera-design.md`); nothing here knows Record3D.

## ROS side (verified facts - do not re-derive)

Both launch files start `rosbridge_websocket` on port 9090 (`rosbridge:=false` disables).
Finger order everywhere: `thumb, index, middle, ring, pinky`.

| topic | type | notes |
|---|---|---|
| `/robot_description` | `std_msgs/String` | URDF XML, latched (transient local); arrives once on subscribe. 7 links, primitives only (boxes), joints `<finger>_joint`, links `<finger>_finger`, root `base_link` (`world` link + fixed mount exist in sim only). Contains `<gazebo>`/`<ros2_control>` tags a URDF parser must ignore. |
| `/joint_states` | `sensor_msgs/JointState` | radians, 0 = open .. 1.57 = closed. ~100 Hz in sim. Names are NOT guaranteed to be in finger order - map by name. |
| `/hand/state` | `std_msgs/Float64MultiArray` | 5 x 0..1 measured, finger order. 50 Hz. |
| `/hand/command` | `std_msgs/Float64MultiArray` | 5 x 0..1 target, finger order. Publishing here moves the hand (the HAL clamps + rate-limits). |
| `/camera/color/image_raw/compressed` | `sensor_msgs/CompressedImage` | JPEG, 640x480, 15 Hz, ~55 KB. `data` is base64 over rosbridge. |
| `/camera/aligned_depth_to_color/camera_info` | `sensor_msgs/CameraInfo` | Intrinsics of the aligned depth (= the colour stream). ROS 2 spells the matrix `k`. Subscribed at 1 Hz; the object placement needs `fx fy cx cy`. |
| `/camera/aligned_depth_to_color/image_raw/compressedDepth` | `sensor_msgs/CompressedImage` | format `16UC1; compressedDepth`. `data` = **12-byte header, then a 16-bit grayscale PNG** (PNG magic `89 50 4E 47` at offset 12). Pixel value = depth in millimetres, 0 = no reading. 640x480, pixel-aligned to the color image, 15 Hz, ~20 KB. |
| `/head_camera/color/image_raw/compressed` | `sensor_msgs/CompressedImage` | The head camera (an iPhone, `head_camera:=iphone`; default `none`). JPEG, 640x480, landscape, max 15 Hz. The node fixes rotation and size. No depth. |
| `/head_camera/aligned_depth_to_color/image_raw/compressedDepth` + `/head_camera/color/camera_info` | `sensor_msgs/CompressedImage`, `sensor_msgs/CameraInfo` | The iPhone's LiDAR depth on the pixels of its colour picture (16UC1 mm), throttled to 5 Hz. Not shown: the object detector takes the head camera (colour + this depth) while the wrist camera has been silent for 2 s, so a bench with only the phone still gets a map. The objects are then where the head sees them, drawn around the hand all the same. |

rosbridge subscribe rules: **always pass `queue_length=1` together with `throttle_rate`** (throttle without a queue length silently drops to ~1.6 Hz). Measured fine: joint states at 30-100 Hz alongside both image streams at 15 Hz, rosbridge at ~12 % CPU. Use `throttle_rate=16` for joint/hand state (the viewer animates from them) and `66` for images.

Either camera may be absent (`camera:=none`, `head_camera:=none`) and ROS may be down entirely; both are normal states the UI must show gracefully, never crash on.

## Backend API (port 8000)

Env: `ROSBRIDGE_HOST` (default `localhost`), `ROSBRIDGE_PORT` (`9090`), `MOCK` (`0`; `1` = no ROS at all, synthesize everything, for UI work and tests), `DETECT_MODEL` (`yolov8n.pt`; an Ultralytics model for the objects around the hand, `""` = off; needs `requirements-detect.txt`, otherwise one warning and no objects), `DETECT_HZ` (`4`, passes per second at most) and `DETECT_THREADS` (`2`, torch threads: the detector shares the machine with the sim and the browser), `MOCK_OBJECTS` (`0`; `1` = live ROS but synthetic objects, for a sim that has no camera), `CORS_ORIGINS` (default `http://localhost:3000,http://127.0.0.1:3000`; also the allow-list for websocket `Origin` headers - a browser page from anywhere else is closed with 1008, clients that send no Origin are accepted).

The backend reconnects to rosbridge forever with backoff and never exits because ROS is down.

### `GET /api/health`
```json
{"ros_connected": true, "mock": false, "rosbridge_url": "ws://localhost:9090",
 "topics": {"joint_states": {"hz": 99.8, "age_ms": 12}, "hand_state": {...}, "hand_command": {...}, "color": {...}, "depth": {...}}}
```
`hz` = messages/s received from ROS over the last ~2 s, `age_ms` = ms since the last one (`null` if never).

### `GET /api/meshes/{name}.stl`, `GET /api/linkage`
The hand's meshes and linkage geometry are files of `htn_description` (env `DESCRIPTION_DIR`, default: this repo's package), not topics. `meshes/<name>` serves the STL behind a URDF visual `package://htn_description/meshes/<name>` (millimetres, CAD frame). `linkage` is `config/linkage.yaml` as JSON: per finger the ten pivots, the closing sense and the limits. The URDF is a tree and cannot say where its loops close, and nobody publishes passive joints for the COMMANDED pose, so the viewer solves the linkage itself (`components/hand/linkage.ts`, a port of `htn_control/linkage.py`, equal to 1e-14 rad).

### `GET /api/urdf`
`200 text/xml` - the latest `/robot_description`. `503` until one has arrived. In mock mode serve a bundled copy (`backend/mock/hand.urdf`, generated once from the real xacro).

### `WS /ws/state`
Server -> client, JSON text, one message every 16.7 ms (60 Hz, one per display frame) regardless of ROS rates (latest-value sampling):
```json
{"t": 1789796072.667,
 "ros_connected": true,
 "fingers": ["thumb","index","middle","ring","pinky"],
 "objects": [],
 "joints":  {"thumb_joint": 1.57, "index_joint": 0.0, "middle_joint": 0.0, "ring_joint": 0.0, "pinky_joint": 0.0},
 "state":   [1.0, 0.0, 0.0, 0.0, 0.0],
 "command": [1.0, 0.0, 0.0, 0.0, 0.0],
 "rates":   {"joint_states": 99.8, "hand_state": 50.0, "hand_command": 0.0, "color": 15.0, "depth": 15.0, "iphone": 15.0, "objects": 8.0}}
```
`passive` (bool, also in the JSON above as `"passive": false`) mirrors the HAL's latched `/hand/passive`: torque off, a person moves the fingers, `/hand/command` is ignored.

`objects` (also in the JSON above, between `passive` and `rates`) is the surroundings: every object the backend currently tracks, oldest first.
```json
"objects": [{"id": 3, "label": "bottle", "xyz": [0.42, 0.11, -0.03], "size": [0.07, 0.07, 0.22], "confidence": 0.86, "age": 0.0, "hits": 41}]
```
`xyz` and `size` are metres in the wrist camera's frame, `camera_link` of the URDF (x forward, y left, z up). The camera is fixed to the hand, so this is a position relative to the hand, and the viewer hangs the objects under that link. `age` is seconds since the last detection: `0` = in view; a track that is not detected any more is dropped after `MEMORY_S` = 1 s (`app/objects.py`), which is the time the page takes to fade it out (`world-layer.tsx`: from 0.4 s to 1.0 s of `age`). The pipeline: `DETECT_MODEL` (Ultralytics YOLO on the CPU, told to look only for the labels of `DETECT_LABELS` in `app/objects.py` - `bottle` so far) on the colour JPEG -> median aligned depth under the middle of each box -> pinhole projection with the `camera_info` intrinsics (a D435 default until it arrives) -> a nearest-neighbour tracker with a 20 cm gate per label; `rates.objects` is the detector's pass rate. `MOCK=1` and `MOCK_OBJECTS=1` feed the same tracker with a synthetic table of objects, one of which leaves the view for a few seconds of every cycle. `joints` are radians by joint name; `state`/`command` are 0..1 in finger order (`command` is `null` until someone has published one). When ROS is down, keep sending with `ros_connected: false` and the last known values.

Client -> server, JSON text:
```json
{"type": "command", "data": [0.0, 1.0, 1.0, 0.0, 0.0]}
```
-> published to `/hand/command` (values clamped to 0..1, must be exactly 5; anything else is ignored).
```json
{"type": "passive", "data": true}
```
-> calls `/hand/set_passive` (`std_srvs/SetBool`); the result comes back as `passive` in the state. The Backdrive switch in the command block sends it (only while armed) and locks the sliders and presets while it is on.

### `WS /ws/camera/realsense/{color|depth}`, `WS /ws/camera/iphone/color`
Three streams, same protocol (`iphone` is the head camera: the source keeps that name in the API; it has no depth, and any other pair is closed with 1008). The page opens only the one each panel is showing, and the backend only renders streams that have a viewer (`LatestChannel.viewers`). Client -> server, text `ready`: the server sends the next (newest) frame only after it, so a slow page is one frame behind at most and never watches a backlog; a client that never sends it is streamed as fast as frames come (a websocket's send buffer is unbounded, and on a busy laptop that backlog reached minutes). The page sends it on open and on every frame received. Server -> client, **binary** messages, each one complete JPEG. Latest-frame only: if the client is slow, drop frames, never queue.
- `color`: the ROS JPEG bytes passed through untouched, for both cameras (the head camera node has already rotated, shrunk and rate-capped the iPhone image).
- `depth`: decoded (the 16-bit PNG), colorized server-side and re-encoded as JPEG (quality ~80). Colormap: near = warm, far = cool (a desaturated two-hue ramp, far `#2f4a63` `#7f9bb3` `#d9dde0` `#e9c9a8` `#c2410c` near, mirrored in `frontend/src/lib/depth-ramp.ts`), over `DEPTH_MIN_MM=150 .. DEPTH_MAX_MM=2000` (env-overridable); pixels with value 0 (no reading) are rendered as the light UI background `#f6f6f6` so holes look intentional on a white page rather than black.

Right after connect, and whenever it changes, the server also sends a JSON **text** message on the same socket:
```json
{"type": "meta", "width": 640, "height": 480, "hz": 15.0, "available": true, "min_mm": 150, "max_mm": 2000}
```
(`min_mm`/`max_mm` only on depth.) `available: false` = no frame received in the last 2 s.

### Episodes: `GET /api/episodes`, `POST /api/episodes/{record|replay|stop}`
Record what the console sees and play it back, from the Episodes bar of the page (`app/episodes.py`; one recording or replay at a time, anything else is a 409 with a `detail` text).
- `GET` -> `{"session": {...}, "datasets": [{"name", "task", "fps", "episodes": [<frames of episode 0>, ...]}]}`.
- `record` `{"dataset": "exo_grasp", "task": "grasp the bottle"}`: a new episode of that dataset at 30 ticks a second - `/hand/state`, the last `/hand/command` as the action (the state until somebody commands), and the newest colour JPEG of the head camera (`camera1`) and the wrist camera (`camera2`), each written once. `stop` `{"keep": true|false}` saves or discards it and answers like `GET`.
- `replay` `{"dataset", "episode", "what": "action"|"state", "speed": 0.1 .. 4}`: the recorded values are published on `/hand/command` again and the recorded JPEGs take the colour panels (live colour frames are dropped meanwhile, the rates still count them). `stop` ends it.
- The running one is `session` in `/ws/state`: `{"mode": "idle"}` or `{"mode": "recording"|"replaying", "dataset", "episode", "frame", "frames"}` (`frames` null while recording).
- On disk: `RECORDINGS_DIR` (default `policy/datasets/console/`, ignored by git) `/<dataset>/meta.json` + `episode_NNN/frames.jsonl` + `episode_NNN/camera{1,2}/NNNNNN.jpg`. `python -m lerobot_robot_exo_hand.from_console --root <dataset>` (in `policy/`) turns a dataset into a LeRobot one.

### Movements: `GET /api/movements`, `POST /api/movements/{play|stop}`
The pre-written movements of the repo's `movements/` folder (`MOVEMENTS_DIR`; format in its README: a Python file with `TITLE` and `steps()` -> `[(pose, seconds), ...]`), in the Movement dropdown of the Episodes bar (`app/movements.py`).
- `GET` -> `[{"name", "title", "description", "seconds", "error"}]`; a file that does not load is listed with its `error` and cannot be played. Files are read again on every call: an edited movement needs no restart.
- `play` `{"name": "hot_cross_buns"}`: each pose is published on `/hand/command`, then nothing for that step's seconds. 409 with a `detail` while another movement or a replay runs; a movement MAY play while an episode is recorded (that records a demonstration). `stop` ends it; the hand stays where it is.
- The running one is `movement` in `/ws/state`: `null` or `{"name", "title", "step", "steps"}`.
- Teaching (what `mcp_server/` uses; no page for it): `PUT /api/movements/{name}` `{"title", "description", "steps": [{"pose": [5 values], "seconds"}]}` writes `movements/<name>.py`, a readable file with the path as a literal list and a first line that marks it as taught; `GET /api/movements/{name}` gives the steps back with `taught`; `DELETE` removes it. A name is `[a-z][a-z0-9_]*`. A file WITHOUT that first line was written by a person: it is listed, read and played, and a `PUT` or `DELETE` on it is a 409.

### For clients that are not a page: `GET /api/state`, `POST /api/command`
`GET /api/state` is one `/ws/state` message. `POST /api/command` `{"values": [thumb, index, middle, ring, pinky]}` publishes one `/hand/command` (clamped to 0..1, 422 if it is not 5 finite numbers) and answers `{"sent": [...]}`. Unlike the page there is no ARM switch in front of it: whoever can reach the backend can move the hand.

### `WS /ws/mirror`
Mirror teleop (`docs/specs/mirror-teleop-design.md`): the controller's webcam in, `/hand/command` out. One client at a time: a second one is accepted and closed with 1013 and a reason. The frames are tracked (MediaPipe `HandLandmarker`) and dropped; nothing of them reaches ROS.

Client -> server: a binary message = one JPEG frame (320x240 is enough; over 1 MB is dropped; only the newest frame is processed). Text:
```json
{"type": "calibrate", "pose": "open"}
```
(`"open"` or `"fist"`.) The next 0.5 s of frames are averaged as that pose. A capture drops the calibration in use, so the hand holds until both poses are captured again. Anything malformed is ignored.

Server -> client, one text message for each processed frame:
```json
{"mode": "following", "calibrated": true, "capturing": null, "error": null,
 "controller": [0.1, 0.8, 0.8, 0.7, 0.6],
 "command": [0.1, 0.8, 0.8, 0.7, 0.6],
 "landmarks": [[0.41, 0.63], "... 21 image points, x and y in 0..1"]}
```
`mode`: `off` (no calibration: nothing is published), `no_hand` (no hand in the frame: `command` holds its last value), `following` (`command` is the controller's curls). A hand that comes back is followed at once, with no match: the command can jump, and the one-euro filter and the HAL's `max_speed` are what soften it. `command` is published on `/hand/command` only when a finger changes by more than `MIRROR_COMMAND_TOLERANCE`. When the calibration completes, `command` starts as the measured `/hand/state`; the console captures the fist first and the open hand last, so the first thing the hand does is open. `capturing`: the pose being captured, or `null`. `error`: why the last capture failed (`"no_hand"`, or `"range"` = a finger bent too little between open and fist; both poses must be captured again), `null` after the next `calibrate`. `controller` (the controller's curls, filtered) is `null` without a calibration or a hand; `command` is `null` in `off`; `landmarks` is `null` without a hand. The measured state is in `/ws/state`.

Env: `MIRROR_COMMAND_TOLERANCE` (`0.01`), one-euro filter `MIRROR_MIN_CUTOFF` (`1.5` Hz) and `MIRROR_BETA` (`1.0`).

### Mock mode (`MOCK=1`)
No rosbridge connection. Joints: each finger curls on its own smooth, phase-shifted sine so the hand looks alive. Color: a generated moving test image. Depth: a generated moving depth field run through the real colorize path. iPhone: the colour image of the same scene a few seconds later. `/ws/state` commands are accepted and override the animation for 3 s. The 5-vector overrides all fingers; when the 3 s hold expires the mock sets `command` back to `null` (live mode never does). `/ws/mirror` ignores the content of the frames and tracks a synthetic hand that makes the same wave as the mock joints and holds the pose of a running capture; MediaPipe is not loaded. Everything above behaves identically otherwise.

## Frontend

- `NEXT_PUBLIC_BACKEND_URL` (default `http://localhost:8000`); websocket URLs are derived from it.
- One page, one screen, no scrolling at >= 1280x720: a simulator console, not a marketing site.

### Shared code every component builds on (created by the scaffold step)
- `src/lib/config.ts` - backend URLs.
- `src/lib/types.ts` - TypeScript types for every message above.
- `src/lib/sim-store.ts` - zustand store: latest `/ws/state` message, connection status, and `sendCommand(data: number[])`. Owns the `/ws/state` socket with auto-reconnect. three.js code must read it with `useSimStore.getState()` inside `useFrame` (transient), never via React state at 30 Hz.
- Per-frame rules for camera code: never put anything that changes every frame into React state (the hook hands React the same state object unless a value changed), and paint decoded frames from `requestAnimationFrame`, newest only.
- `src/hooks/use-camera-stream.ts` - `useCameraStream(source: 'realsense' | 'iphone', kind: 'color' | 'depth')` (`iphone` has only `color`) -> `{canvasRef, meta, status, fps}`; owns the socket, decodes with `createImageBitmap`, draws to the canvas, auto-reconnects.
- `src/components/ui/*` - shadcn components.
- `src/components/console/panel.tsx` - `<Panel index="01" title="Hand" tag="/joint_states" status=... actions=...>`: the framed viewport chrome every panel uses.

### Components (each owned by exactly one build agent)
- `src/components/hand/hand-viewport.tsx` -> `export function HandViewport()`. The map: `world-layer.tsx` draws range rings (25 cm, 50 cm, 1 m) on the ground and, per tracked object, an outline box portalled under the model's `camera_link`, a drop line and footprint on the ground, a label chip and a dot on the radar (`hand-hud.tsx`); an object in view carries the accent, a remembered one fades with `age`. The `chase` preset sits over the wrist looking past the fingers, and the first objects to appear switch to it once.
- `src/components/camera/camera-viewport.tsx` -> `export function CameraViewport({source}: {source: 'realsense' | 'iphone'})`; the RealSense's RGB / DEPTH toggle lives in the panel header; the iPhone panel with no frames says to start `head_camera:=iphone`
- `src/components/telemetry/telemetry-strip.tsx` -> `export function TelemetryStrip()`; its command block has the Arm, Backdrive and Mirror switches
- `src/components/console/console-stage.tsx` -> `export function ConsoleStage()`: the middle row, left to right 3D hand (01) / RealSense over iPhone (02, 03) / mirror (04). The mirror column is on the very right and is on the page ONLY while the Mirror switch is on: it is `MirrorViewport` (the controller's webcam with the tracked skeleton, the guided calibration, controller / command / state bars), which owns the webcam and `/ws/mirror`, so neither exists while the switch is off. With Mirror off the 3D hand takes the room.
- `src/components/console/top-bar.tsx` -> `export function TopBar()`
- `src/app/page.tsx` composes them: top bar; main row = 3D hand (~46 %) + mirror panel (~27 %) + a column with the RealSense panel over the iPhone panel (~27 %); telemetry strip along the bottom. Panels are numbered 01 hand, 02 mirror, 03 RealSense, 04 iPhone, 05 telemetry. `Panel`'s header is a container: a narrow panel drops its topic tag first, then its status word (the dot stays) unless `keepStatusLabel` is set.

## Design language

Inspiration: eragon.ai - quiet, technical, editorial. Light theme only.

- Colors: page `#f6f6f6`, panel surface `#ffffff`, ink `#242424`, secondary ink `#484848`, muted `#727272`, hairlines `#242424` at 10-14 % opacity. **One** accent, used sparingly for live/active things only. No gradients-as-decoration, no glassmorphism, no neon, no drop-shadow-heavy cards, no dark mode.
- Type: Inter for UI; **Fragment Mono** for every label, number, topic name and unit. Labels are small (10-11 px), uppercase, tracked out. Numbers are tabular.
- Motifs: numbered section labels (`01`, `02`, `03`), slash-prefixed mono tags (`/hand/state`), 1 px hairline frames with small corner ticks, tiny status dots, fine dotted or line grids, coordinates and units in the margins. Radii 0-4 px. Generous whitespace.
- Motion (framer-motion): restrained and precise - staggered fade/slide-in on load, number tweening, smooth layout transitions, a slow pulse on live indicators. Nothing bouncy.
- 3D: a product-render look on a light backdrop - soft key light + environment reflections, contact shadows on a faint ground grid, matte white and graphite materials, thin accent edge highlights. The hand must read as a designed object, not a debug view.
