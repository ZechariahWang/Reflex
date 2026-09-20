# Next work

Where the work stopped, and what to read before the next session. Update this
file at the end of a session; the designs themselves are in `../specs/`.

## State on 2026-09-19

- **Next: run the calibration and tune the contact stop ON THE REAL HAND**, then
  the mirror teleop. The start-up hazards, the contact stop and `servo_tool
  calibrate` are built and tested on the fake servo bus only
  (`../specs/hal-safety-design.md`, "What is built"). On the hand, in this order:
  `servo_tool scan`, `servo_tool calibrate` (a window) with the hand off the wearer,
  a launch, then tune `contact_stop:` and `hold_torque` in `hand_params.yaml`.
- **Mirror teleop: built, tested without hardware, not yet run by a person**
  (`../specs/mirror-teleop-design.md`). Backend `app/mirror/` + `WS /ws/mirror`,
  the Mirror switch and panel (in the 3D hand's place) in the frontend,
  `exo_hand_command` in `policy/`. Left, in this order: the done check of the spec
  with a real webcam against the sim (open, fist, pinch, thumb at ~0.5, dropout),
  tune `MIRROR_MIN_CUTOFF` / `MIRROR_BETA`, two
  `lerobot-record` episodes, the loop rate on one laptop. The thumb measure (joint
  angles) is the part most likely to need a change. On the real hand only the thumb
  moves until the other fingers are calibrated. TODO next to it: the recording
  console spec.
- **Ring and pinky travel too far.** Calibrated travel: ring 101.5 deg of horn, pinky 95.6 deg; the
  linkage has 117 deg (ring) and 129 deg (pinky) between its two binds. The ring is within 8 deg
  of a bind at BOTH ends: near a bind the linkage's leverage goes to infinity, which is the likely
  cause of the broken plastic. Recalibrate the ring with less travel (`servo_tool calibrate`).
  `min_angle` of both in `hand_params.yaml` is an estimate (where the travel lies relative to the
  CAD pose is not measured): check the 3D hand against the real one at open and at closed.
- **The forehead iPhone is a ROS camera** (`../specs/iphone-camera-design.md`):
  `iphone_camera_node` (`head_camera:=iphone`) publishes
  `/head_camera/color/image_raw/compressed`, `ExoHand` has it as `camera1`, the web
  backend only passes it through. Tested on a fake phone only. Left: plug the phone in
  (Record3D, USB Streaming mode, NOT recording), `ros2 topic hz
  /head_camera/color/camera_info` must show ~15 Hz, check in Foxglove that the image is
  the right way up on the forehead mount (`rotation`) BEFORE the first recording.
- **Calibrated on the hand so far: the thumb** (open 1511, closed 2208 = 61 deg of
  horn; its `max_angle` is that travel). index .. pinky are `enabled: false` in
  `hand_params.yaml`: the HAL never gives them torque or a goal, whatever is
  commanded, until they are saved in the calibration window (that enables them and
  sets their `max_angle`). The web console drives the real hand as it is:
  `hardware.launch.py` + `application/dev.sh`, ARM, sliders.
- **The other fingers still have PLACEHOLDER calibration** (`open_step: 2048` for
  every finger; the span is now the linkage's `max_angle`, no longer 90 deg,
  which would have driven middle and ring into their bind at 84 deg). The HAL no
  longer drives anywhere at start: it holds the measured pose. A command still
  moves the fingers within the placeholder range, so keep the hand off the
  wearer until the calibration has run.
- The adapter passes its supply straight to the servos: these are the 7.4 V
  STS3215, so 6 .. 8.4 V on the adapter, never 12 V.
- **Backdrive is closed** for these servos: too stiff with the torque off, and
  an encoder-only active backdrive did not give a light start
  (`../specs/data-collection-design.md`, Backdrive result). Do not start it
  again unless the hardware changes (force sensor, elastic link, lower gear
  ratio).
- Left of the contact stop's work order: the tuning on the hand (the
  `blocked_*` values, `release_travel`, `hold_torque`, then `torque_limit` back up for speed).
  The three steps are in `docs/specs/contact-stop-release-design.md`, "On the hand".

- **Lambda training: built, no rental run yet** (`../specs/lambda-training-design.md`,
  `policy/README.md`, Training on a rented Lambda GPU). Tested here: the split and the error math
  (`pytest`), the watchdog rules and `run_logged.sh` (shell tests with a fake instance), and one
  CPU run of generator -> split -> `lerobot-train --dataset.episodes` -> `heldout eval`.
  `launch.sh`, `setup.sh` and `pull.sh` have run nowhere. Left, in this order: fill
  `policy/lambda/.env` (Lambda key, ssh key name, `claude setup-token`), `launch.sh --dry-run`,
  `launch.sh --smoke-scripts`, `launch.sh --smoke`, then a real dataset and `plan.md`. Not
  verified: that the token gives Opus, the `lerobot-train` option names of the variants, the
  speed of the evaluation on a GPU.

## Done and working

- Recorder: `exo_hand_leader`, `--robot.passive`, the `/hand/passive` checks;
  `label.py`; record + label ran end to end without hardware.
- Training: `lerobot-train` dry run on a CPU (10 steps), command in
  `policy/README.md`. The 5-value state and action need no model change.
- Servo ids 1 (thumb) .. 5 (pinky) set on the real hand; the HAL finds all 5.

## Not run yet

- The inference loop (`policy_server` + `robot_client`), with any checkpoint.
- Anything with a real camera on this laptop: the ROS container (Kilted) has no
  RealSense driver and no Gazebo. Use `hardware.launch.py camera:=none`, and
  run `physical_layer/build.sh` after a pull that adds files.
