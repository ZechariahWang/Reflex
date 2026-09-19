# Next work

Where the work stopped, and what to read before the next session. Update this
file at the end of a session; the designs themselves are in `../specs/`.

## State on 2026-09-19

- **Next: run the calibration and tune the contact stop ON THE REAL HAND**, then
  the mirror teleop. The start-up hazards, the contact stop and `servo_tool
  calibrate` are built and tested on the fake servo bus only
  (`../specs/hal-safety-design.md`, "What is built"). On the hand, in this order:
  `servo_tool scan`, `servo_tool calibrate --write` with the hand off the wearer,
  a launch, then tune `contact_stop:` and `hold_torque` in `hand_params.yaml`.
- **The real hand still has PLACEHOLDER calibration** (`open_step: 2048` for
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
  `blocked_*` values, `hold_torque`, then `torque_limit` back up for speed).

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
