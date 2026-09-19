# backend

FastAPI bridge between rosbridge (`ws://localhost:9090`) and the browser. API: `../CONTRACT.md`.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # setup
.venv/bin/uvicorn app.main:app --port 8000                               # run (ROS may be down; it reconnects forever)
MOCK=1 .venv/bin/uvicorn app.main:app --port 8000                        # mock mode: no ROS, synthetic hand + cameras
.venv/bin/python -m pytest -q                                            # tests
```

Env: `ROSBRIDGE_HOST` (localhost), `ROSBRIDGE_PORT` (9090), `MOCK` (0), `CORS_ORIGINS` (http://localhost:3000,http://127.0.0.1:3000;
comma-separated), `DEPTH_MIN_MM` (150), `DEPTH_MAX_MM` (2000), `RECORD3D_HOST` (empty; the iPhone panel normally sets it).

iPhone: `app/record3d.py` is the Record3D client - `usb` (cable, any network) or the phone's Wi-Fi address (WebRTC). No phone around?
`.venv/bin/python -m tests.fake_record3d --port 8099`, then enter `localhost:8099` in the iPhone panel.

`mock/hand.urdf` is generated from `htn_description/urdf/hand.urdf.xacro`; regenerate it if the xacro changes.
