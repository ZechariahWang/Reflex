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
- `docs/` - design documents. Read `docs/system-design.md` (devices, ROS
  layout, policy, safety, open questions) before design work. Specs for single features go in `docs/specs/`.
- (planned) a separate top-level folder for the VLA / policy code (training,
  datasets, inference). It stays plain Python outside ROS so torch & co. never
  enter the colcon build; `htn_auto` in the ROS workspace is the thin bridge.

## Contracts that cross folders

- Finger order is always `thumb, index, middle, ring, pinky`.
- Anything that wants to move the hand publishes `/hand/command`
  (`std_msgs/Float64MultiArray`, 5 values, `0` = open .. `1` = closed) and reads
  `/hand/state` (same layout, measured). Nothing outside the HAL uses radians,
  servo steps or serial.
- Anything that wants to see reads the camera from `/camera/color/image_raw`
  (`sensor_msgs/Image`, rgb8, + `/compressed`), `/camera/depth/image_rect_raw`
  and `/camera/aligned_depth_to_color/image_raw` (16UC1, millimetres), each
  with a `camera_info` next to it. Nothing outside the camera launch file knows
  it is a RealSense.
- Physical numbers (sizes, masses, angle limits, servo calibration) live only in
  `physical_layer/ros2_ws/src/htn_description/config/hand_params.yaml`.

## Conventions

- **Commit automatically.** After every completed change (a fix, a feature, a
  doc update) commit it right away without asking: `git add -A :/` from
  anywhere in the repo, one commit per logical change, message says what and
  why. Verify first (tests / build for the part you touched) - never commit a
  known-broken state. Do NOT push; pushing stays a manual step.
- Keep it bare-bones: this is a hackathon project, prefer the smallest thing
  that works over frameworks and abstraction.
- Build with `physical_layer/build.sh`. Never run `colcon build` from the repo
  root: colcon drops `build/ install/ log/` into whatever directory it runs in.
- Safety limits for the real hand belong in the HAL and the servo registers, below any
  learned policy.
