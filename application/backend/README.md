# backend

FastAPI bridge between rosbridge (`ws://localhost:9090`) and the browser. API: `../CONTRACT.md`.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # setup
.venv/bin/uvicorn app.main:app --port 8000                               # run (ROS may be down; it reconnects forever)
MOCK=1 .venv/bin/uvicorn app.main:app --port 8000                        # mock mode: no ROS, synthetic hand + cameras
.venv/bin/python -m pytest -q                                            # tests
```

Env: `ROSBRIDGE_HOST` (localhost), `ROSBRIDGE_PORT` (9090), `MOCK` (0), `CORS_ORIGINS` (http://localhost:3000,http://127.0.0.1:3000;
comma-separated), `DEPTH_MIN_MM` (150), `DEPTH_MAX_MM` (2000), `MIRROR_*` (mirror teleop tuning, see `../CONTRACT.md`).

iPhone: a ROS camera like the RealSense (`/head_camera/color/image_raw/compressed`, from `camera.launch.py head_camera:=iphone`);
the backend passes its JPEGs through. The phone itself (Record3D, USB) belongs to the ROS node. No phone around? `MOCK=1`.

Mirror teleop: `app/mirror/` tracks the controller's webcam frames from `/ws/mirror` with MediaPipe (`models/hand_landmarker.task`, Google's
pretrained float16 model, in the repo so nothing downloads at run time). The pinned numpy needs Python <= 3.13 for the venv.

`mock/hand.urdf` is generated from `htn_description/urdf/hand.urdf.xacro`; regenerate it if the xacro changes.
