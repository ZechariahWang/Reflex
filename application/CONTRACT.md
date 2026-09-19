# application/ - web simulator

A web console for the exoskeleton hand: a three.js viewport of the hand moving
live, plus the RealSense color view and a colorized depth view. It is a pure
consumer of the ROS topics in `physical_layer/`; it works identically whether
the hand is simulated (`sim.launch.py`) or real (`hardware.launch.py`).

```
physical_layer (ROS 2)  --rosbridge ws://localhost:9090-->  backend (FastAPI :8000)  --ws/http-->  frontend (Next.js :3000)
```

- `backend/`  - FastAPI + `roslibpy`. The only thing that talks to ROS.
- `frontend/` - Next.js (App Router, TypeScript), Tailwind, shadcn/ui, framer-motion (`motion`), three.js via `@react-three/fiber` + `drei`, `urdf-loader`.

The browser never talks to rosbridge directly.

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
| `/camera/aligned_depth_to_color/image_raw/compressedDepth` | `sensor_msgs/CompressedImage` | format `16UC1; compressedDepth`. `data` = **12-byte header, then a 16-bit grayscale PNG** (PNG magic `89 50 4E 47` at offset 12). Pixel value = depth in millimetres, 0 = no reading. 640x480, pixel-aligned to the color image, 15 Hz, ~20 KB. |

rosbridge subscribe rules: **always pass `queue_length=1` together with `throttle_rate`** (throttle without a queue length silently drops to ~1.6 Hz). Measured fine: joint states at 30-100 Hz alongside both image streams at 15 Hz, rosbridge at ~12 % CPU. Use `throttle_rate=33` for joint/hand state and `66` for images.

The camera may be absent (`camera:=none`) and ROS may be down entirely; both are normal states the UI must show gracefully, never crash on.

## Backend API (port 8000)

Env: `ROSBRIDGE_HOST` (default `localhost`), `ROSBRIDGE_PORT` (`9090`), `MOCK` (`0`; `1` = no ROS at all, synthesize everything, for UI work and tests), `CORS_ORIGINS` (default `http://localhost:3000`).

The backend reconnects to rosbridge forever with backoff and never exits because ROS is down.

### `GET /api/health`
```json
{"ros_connected": true, "mock": false, "rosbridge_url": "ws://localhost:9090",
 "topics": {"joint_states": {"hz": 99.8, "age_ms": 12}, "hand_state": {...}, "hand_command": {...}, "color": {...}, "depth": {...}}}
```
`hz` = messages/s received from ROS over the last ~2 s, `age_ms` = ms since the last one (`null` if never).

### `GET /api/urdf`
`200 text/xml` - the latest `/robot_description`. `503` until one has arrived. In mock mode serve a bundled copy (`backend/mock/hand.urdf`, generated once from the real xacro).

### `WS /ws/state`
Server -> client, JSON text, one message every 33 ms (30 Hz) regardless of ROS rates (latest-value sampling):
```json
{"t": 1789796072.667,
 "ros_connected": true,
 "fingers": ["thumb","index","middle","ring","pinky"],
 "joints":  {"thumb_joint": 1.57, "index_joint": 0.0, "middle_joint": 0.0, "ring_joint": 0.0, "pinky_joint": 0.0},
 "state":   [1.0, 0.0, 0.0, 0.0, 0.0],
 "command": [1.0, 0.0, 0.0, 0.0, 0.0],
 "rates":   {"joint_states": 99.8, "hand_state": 50.0, "hand_command": 0.0, "color": 15.0, "depth": 15.0}}
```
`joints` are radians by joint name; `state`/`command` are 0..1 in finger order (`command` is `null` until someone has published one). When ROS is down, keep sending with `ros_connected: false` and the last known values.

Client -> server, JSON text:
```json
{"type": "command", "data": [0.0, 1.0, 1.0, 0.0, 0.0]}
```
-> published to `/hand/command` (values clamped to 0..1, must be exactly 5; anything else is ignored).

### `WS /ws/camera/color` and `WS /ws/camera/depth`
Server -> client, **binary** messages, each one complete JPEG. Latest-frame only: if the client is slow, drop frames, never queue.
- `color`: the ROS JPEG bytes passed through untouched.
- `depth`: decoded from the 16-bit PNG, colorized server-side and re-encoded as JPEG (quality ~80). Colormap: near = warm, far = cool, over `DEPTH_MIN_MM=150 .. DEPTH_MAX_MM=2000` (env-overridable); pixels with value 0 (no reading) are rendered as the light UI background `#f6f6f6` so holes look intentional on a white page rather than black.

Right after connect, and whenever it changes, the server also sends a JSON **text** message on the same socket:
```json
{"type": "meta", "width": 640, "height": 480, "hz": 15.0, "available": true, "min_mm": 150, "max_mm": 2000}
```
(`min_mm`/`max_mm` only on depth.) `available: false` = no frame received in the last 2 s.

### Mock mode (`MOCK=1`)
No rosbridge connection. Joints: each finger curls on its own smooth, phase-shifted sine so the hand looks alive. Color: a generated moving test image. Depth: a generated moving depth field run through the real colorize path. `/ws/state` commands are accepted and override the animation for that finger for 3 s. Everything above behaves identically otherwise.

## Frontend

- `NEXT_PUBLIC_BACKEND_URL` (default `http://localhost:8000`); websocket URLs are derived from it.
- One page, one screen, no scrolling at >= 1280x720: a simulator console, not a marketing site.

### Shared code every component builds on (created by the scaffold step)
- `src/lib/config.ts` - backend URLs.
- `src/lib/types.ts` - TypeScript types for every message above.
- `src/lib/sim-store.ts` - zustand store: latest `/ws/state` message, connection status, a rolling history (last ~10 s) of `state` per finger for sparklines, and `sendCommand(data: number[])`. Owns the `/ws/state` socket with auto-reconnect. three.js code must read it with `useSimStore.getState()` inside `useFrame` (transient), never via React state at 30 Hz.
- `src/hooks/use-camera-stream.ts` - `useCameraStream(kind: 'color' | 'depth')` -> `{canvasRef, meta, status, fps}`; owns the socket, decodes with `createImageBitmap`, draws to the canvas, auto-reconnects.
- `src/components/ui/*` - shadcn components.
- `src/components/console/panel.tsx` - `<Panel index="01" title="Hand" tag="/joint_states" status=... actions=...>`: the framed viewport chrome every panel uses.

### Components (each owned by exactly one build agent)
- `src/components/hand/hand-viewport.tsx` -> `export function HandViewport()`
- `src/components/camera/camera-viewport.tsx` -> `export function CameraViewport({kind}: {kind: 'color' | 'depth'})`
- `src/components/telemetry/telemetry-strip.tsx` -> `export function TelemetryStrip()`
- `src/components/console/top-bar.tsx` -> `export function TopBar()`
- `src/app/page.tsx` composes them: top bar; main row = hand viewport (~62 % width) + a right column with color over depth; telemetry strip along the bottom.

## Design language

Inspiration: eragon.ai - quiet, technical, editorial. Light theme only.

- Colors: page `#f6f6f6`, panel surface `#ffffff`, ink `#242424`, secondary ink `#484848`, muted `#727272`, hairlines `#242424` at 10-14 % opacity. **One** accent, used sparingly for live/active things only. No gradients-as-decoration, no glassmorphism, no neon, no drop-shadow-heavy cards, no dark mode.
- Type: Inter for UI; **Fragment Mono** for every label, number, topic name and unit. Labels are small (10-11 px), uppercase, tracked out. Numbers are tabular.
- Motifs: numbered section labels (`01`, `02`, `03`), slash-prefixed mono tags (`/hand/state`), 1 px hairline frames with small corner ticks, tiny status dots, fine dotted or line grids, coordinates and units in the margins. Radii 0-4 px. Generous whitespace.
- Motion (framer-motion): restrained and precise - staggered fade/slide-in on load, number tweening, smooth layout transitions, a slow pulse on live indicators. Nothing bouncy.
- 3D: a product-render look on a light backdrop - soft key light + environment reflections, contact shadows on a faint ground grid, matte white and graphite materials, thin accent edge highlights. The hand must read as a designed object, not a debug view.
