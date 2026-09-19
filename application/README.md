# application/ - hand simulator console

![Hand Console](docs/screenshot.png)

A one-screen web console for the exoskeleton hand: a three.js viewport of the hand
moving live, a RealSense panel and an iPhone (Record3D) panel that each switch between
RGB and colorized depth, per-finger telemetry,
and an ARM-gated command block. It only consumes ROS topics from `physical_layer/`,
so it looks the same for the Gazebo sim and the real hardware.
```
physical_layer (ROS 2) --rosbridge ws :9090--> backend (FastAPI :8000) --ws/http--> frontend (Next.js :3000)
```

- `backend/`  - FastAPI + roslibpy. The only thing that talks to ROS. Caches the latest
  value of every topic, colorizes depth, serves `/api/health`, `/api/urdf`, `/ws/state`,
  `/ws/camera/{realsense,iphone}/{color,depth}`. Reconnects to rosbridge forever. It is also
  the WebRTC peer of the iPhone (Record3D Wi-Fi streaming), since the phone allows one viewer.
- `frontend/` - Next.js, Tailwind, shadcn/ui, motion, three.js (@react-three/fiber, urdf-loader).
- `CONTRACT.md` - every API shape, topic and design rule. Read it before changing either side.

## Run

```bash
# terminal 1 - the ROS side (starts rosbridge on :9090; hardware.launch.py works the same)
ros2 launch htn_launch sim.launch.py

# terminal 2 - backend + frontend, Ctrl-C stops both
./dev.sh                # then open http://localhost:3000
MOCK=1 ./dev.sh         # no ROS at all: synthetic hand, color and depth
```

`dev.sh` creates `backend/.venv` and `frontend/node_modules` on first run. Start order does
not matter: with ROS down the console shows OFFLINE / NO SIGNAL and recovers on its own.

| env | default | |
|---|---|---|
| `MOCK` | `0` | `1` = synthesize everything |
| `RECORD3D_HOST` | empty | iPhone address, or `usb` for the cable; normally set from the iPhone panel instead |
| `ROSBRIDGE_HOST` / `ROSBRIDGE_PORT` | `localhost` / `9090` | where rosbridge listens |
| `BACKEND_PORT` / `FRONTEND_PORT` | `8000` / `3000` | dev.sh ports |
| `DEPTH_MIN_MM` / `DEPTH_MAX_MM` | `150` / `2000` | depth colormap range |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | pages allowed to call the API and open its websockets |

Viewing from another machine needs `CORS_ORIGINS=http://<host>:3000`, `NEXT_PUBLIC_BACKEND_URL=http://<host>:8000`
and uvicorn started with `--host 0.0.0.0`.

Commands only leave the page while the ARM switch is on; it disarms itself when ROS drops.

Checks: `backend/.venv/bin/pytest` (needs `requirements-dev.txt`); in `frontend/`: `npx tsc --noEmit && npx eslint . && npm run build`.
