# Mirror teleop: the free hand commands the exoskeleton

How the demonstrations are made now that backdrive is not usable
(`data-collection-design.md`, Backdrive result). Status: design notes from the
discussion of 2026-09-19, nothing implemented, nothing verified.

## Decisions

- Record with the torque ON. The action is the command on `/hand/command`, the
  observation is the wrist camera and `/hand/state`, as before.
- The commands come from the other (free) hand of the wearer or of a second
  person: a webcam sees that hand and the exoskeleton copies its finger curl.
  This gives human timing (the reason for the backdrive idea) and commands that
  go past the contact point, so the grip intent is in the labels.
- Hand detection: **MediaPipe Hands**. It is a pretrained model (21 landmarks
  for each hand and frame, runs on a CPU in real time). **No training of ours.**
  The only per-person step is a short calibration: open hand, then fist, to
  scale each finger to `0..1`.
- It is also a possible product mode ("mirror my good hand"), not only a data
  collection tool.

## Components

1. **Command teleoperator** in `policy/lerobot_robot_exo_hand`: a LeRobot
   `Teleoperator` whose `get_action()` is the last message on `/hand/command`
   (~10 lines and a test; `ExoHandLeader` is the pattern). Record with
   `--robot.passive=true` (the adapter must not publish the commands again) and
   with this teleoperator instead of `exo_hand_leader`. It makes a recording
   with the keys or the hold-to-move buttons possible before the mirror exists.
2. **Mirror script** in `policy/`, plain Python, no ROS: webcam -> MediaPipe ->
   one curl value for each finger -> filter -> `/hand/command` through
   rosbridge (`roslibpy`).
   - Curl from the landmarks: the joint angles of each finger, or the distance
     fingertip to wrist divided by the palm size. The thumb is the hard one.
   - Filter: a one-euro filter on each curl value. Hand tracking jitters by
     some percent; without a filter the labels shake and the policy learns to
     shake. The HAL rate limit (`max_speed`) and the servo acceleration are the
     second and third smoothing stage.
   - Tracking lost (hand turned away, covered, bad light): hold the last
     value, publish nothing.
   - Obey the `/hand/command` rule of `physical_layer/CLAUDE.md`: publish only
     on change (a deadband), never on a timer.
   - Pure parts (curl, filter, calibration scaling) get tests with no camera.
3. **Labels**: `label.py` stays. With commands as the source, `gain = 0` (the
   command has the intent past contact already) and `k` small or `0` (the
   command leads the state by itself). `label.py` reads `observation.state`
   today; for command recordings it must label from the recorded `action`, or
   the recording is used with no relabel. Decide when the first recording
   exists.

## Expected behaviour

- Delay from the free hand to the exoskeleton ~0.1 to 0.15 s. Visible, no harm
  to the data: the label is the command.
- The free hand is busy during a demonstration. Fine for a grasp with the
  exoskeleton hand; no two-hand tasks.

## Open / not verified

- MediaPipe wheels for Python 3.12 (the `policy/` venv). Not checked.
- The contact stop of the HAL (`hal-safety-design.md`) matters more with this
  method: the mirror commands "past contact" all the time.
- The ROS container on the development laptop has no RealSense driver: no
  wrist camera topic there. Install it, or record on the machine that has it.
