# htn-2026

Assistive exoskeleton hand: 5 fingers, each one servo / 1 DOF (curl only). Goal
is a hand that detects what the wearer wants (grasp a bottle, play piano) and
moves the fingers for them. Developed sim-first, then deployed to real bus
servos on a USB adapter (no microcontroller of ours).

## Layout

Monorepo. The repo root holds only `README.md`, `CLAUDE.md` and `.gitignore`;
everything else goes in a top-level subfolder per concern.

- `physical_layer/` - ROS 2 workspace: hand model, sim, HAL, teleop. See
  `physical_layer/CLAUDE.md` before touching anything in there.
- `application/` - web simulator / console: FastAPI backend (`backend/`) that
  reads the ROS topics through rosbridge (`ws://localhost:9090`, started by both
  launch files) and a Next.js + three.js frontend (`frontend/`). A pure consumer
  of the contracts below; interfaces are in `application/CONTRACT.md`.
- `movements/` - pre-written movements of the hand (hot cross buns on three keys, ...): one small
  Python file each, listed and played by the web console. Format in `movements/README.md`.
- `mcp_server/` - an MCP server (Python, its own venv, no ROS): any MCP client can read the hand,
  move it, run skills and teach new ones. A skill is a taught movement = a hard-coded path saved
  into `movements/`. A thin client of the web backend's HTTP API. See `mcp_server/README.md`.
- `docs/` - design documents. Read `docs/system-design.md` (devices, ROS
  layout, policy, safety, open questions) before design work. Specs for single features go in `docs/specs/`.
  `docs/notes/next-work.md` says where the work stopped: read it at the start of a session.
- `policy/` - the learned policy side, plain Python (>= 3.12) outside ROS so
  torch & co. never enter the colcon build. `lerobot_robot_exo_hand` is the
  LeRobot `Robot` for the hand; it runs on the GPU laptop and reaches the
  contracts below through rosbridge, never through `rclpy`. Training, datasets
  and inference scripts go here too. See `docs/specs/policy-link-design.md`.

## Contracts that cross folders

- Finger order is always `thumb, index, middle, ring, pinky`.
- Anything that wants to move the hand publishes `/hand/command`
  (`std_msgs/Float64MultiArray`, 5 values, `0` = open .. `1` = closed) and reads
  `/hand/state` (same layout, measured). Nothing outside the HAL uses radians,
  servo steps or serial.
- Backdrive (passive) mode, for recording demonstrations: call
  `/hand/set_passive` (`std_srvs/SetBool`) and the HAL cuts the torque, ignores
  `/hand/command` and keeps publishing `/hand/state` from the encoders while a
  person moves the fingers. `/hand/passive` (`std_msgs/Bool`, latched) reports
  the mode. Leaving it holds the pose the fingers are in and publishes that pose
  once on `/hand/command`. A recorder needs only `/hand/state` and the camera.
- Anything that wants to see reads the camera from `/camera/color/image_raw`
  (`sensor_msgs/Image`, rgb8, + `/compressed`), `/camera/depth/image_rect_raw`
  and `/camera/aligned_depth_to_color/image_raw` (16UC1, millimetres), each
  with a `camera_info` next to it. Nothing outside the camera launch file knows
  it is a RealSense.
- The head camera is `/head_camera/color/image_raw/compressed`
  (`sensor_msgs/CompressedImage`, `jpeg`, 640 x 480, landscape, max 15 fps) with
  `/head_camera/color/camera_info` next to it. `header.stamp` is the ROS time at
  which the frame arrived; `frame_id` is `head_camera_color_optical_frame` (no TF:
  the head is not attached to the hand). Its LiDAR depth, on the pixels of that
  picture (so the same `camera_info`), is
  `/head_camera/aligned_depth_to_color/image_raw/compressedDepth` (16UC1,
  millimetres): for the console's object map, not for the policy. Nothing
  outside the camera launch file knows it is an iPhone.
- Physical numbers (sizes, masses, angle limits, servo calibration) live only in
  `physical_layer/ros2_ws/src/htn_description/config/hand_params.yaml`.

## Conventions

- **Commit automatically.** After every completed change (a fix, a feature, a
  doc update) commit it right away without asking: `git add -A :/` from
  anywhere in the repo, one commit per logical change, message says what and
  why. Verify first (tests / build for the part you touched) - never commit a
  known-broken state. Then `git pull --rebase` and `git push` (a teammate
  pushes to `origin/main` too, so always rebase, never merge or force-push; on
  a rebase conflict stop and say so instead of guessing).
- Keep it bare-bones: this is a hackathon project, prefer the smallest thing
  that works over frameworks and abstraction.
- Build with `physical_layer/build.sh`. Never run `colcon build` from the repo
  root: colcon drops `build/ install/ log/` into whatever directory it runs in.
- Safety limits for the real hand belong in the HAL and the servo registers, below any
  learned policy.
