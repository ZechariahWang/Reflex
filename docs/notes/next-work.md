# Next work

Where the work stopped, and what to read before the next session. Update this
file at the end of a session; the designs themselves are in `../specs/`.

## State on 2026-09-19

- **Next: calibration and motor safety on the real hand**, then the mirror
  teleop. Read `../specs/hal-safety-design.md` first (state of the hand, the
  hazards, the contact stop, the calibration, the work order), then
  `../specs/mirror-teleop-design.md`. Both are design notes; nothing of them is
  implemented.
- **The real hand has PLACEHOLDER calibration** (`open_step: 2048`,
  `closed_step: 3072` for every finger). A launch without `passive:=true`
  drives every finger to step 2048 with the full torque limit, and the exit of
  passive mode can make a finger jump. Keep the hand out of the exoskeleton at
  each start until `hand_params.yaml` has real values.
- **Backdrive is closed** for these servos: too stiff with the torque off, and
  an encoder-only active backdrive did not give a light start
  (`../specs/data-collection-design.md`, Backdrive result). Do not start it
  again unless the hardware changes (force sensor, elastic link, lower gear
  ratio).
- The contact stop changes HAL code of a teammate (`hal_node.py`,
  `feetech_backend.py`): tell them before the edit.
- Work order of the contact stop: the pure `hal/contact.py` with tests first,
  then the HAL integration on the fake servo bus, then `servo_tool calibrate`
  on the same detector, then the tuning on the hand.

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
