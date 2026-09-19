# HAL safety: calibration and the contact stop

The next work on the real hand. Status: design notes from the discussion and
the hardware tests of 2026-09-19. **Implemented later that day, on the fake
servo bus only** - see "What is built" at the end; nothing of it has run on the
real hand, and the thresholds are untuned.

## State of the real hand (2026-09-19)

- 5 Feetech ST servos on the Waveshare adapter (CH343, `/dev/ttyACM0`, 1 Mbaud).
  They had all the factory id 1 (scan showed a checksum error on id 1: identical
  ping replies overlap cleanly, position replies collide). Numbered with
  `servo_tool set-id`, one servo on the bus at a time: thumb 1 .. pinky 5. The
  HAL finds all 5.
- **The calibration is still the placeholder**: `open_step: 2048`,
  `closed_step: 3072` for every finger in `hand_params.yaml`.
- The development laptop runs ROS **Kilted** in the distrobox `ros` (no Gazebo,
  no `ros2_control`, no RealSense driver): use `hardware.launch.py camera:=none`.
  After a pull that adds files, run `physical_layer/build.sh`.

## Hazards found

1. **Placeholder calibration + active launch**: the HAL starts with the
   setpoint "open" (step 2048), not with the measured pose, and drives there
   with the full torque limit. `max_speed` does not help.
2. **Exit of passive mode**: the HAL clamps the measured pose to `0..1` and
   makes it the goal before the torque comes on. A finger outside the
   (placeholder) range jumps to the range edge.
3. **Torque pulse at start with `passive:=true`**: `FeetechBackend.__init__`
   enables the torque for every servo before the HAL sets it off. A servo that
   kept power can hold an old goal for some milliseconds. Fix: do not enable the
   torque when the start is passive.
4. `servo_tool scan` stops at the first servo with a bad read, so it does not
   diagnose "several servos on one id". Fix: catch the error, print it, go on.

## What the torque limit does (measured)

Register 48 caps the drive duty cycle. It lowers the speed AND the stall
torque together: at 100 of 1000 the finger is slow and still does not stall on
a hand. It is the safety ceiling, not a grip-force control. Force and speed
need separate knobs.

## Contact stop (the motor stop that protects the parts)

Purpose: a finger that meets resistance, in ANY direction, must stop pushing
hard. This protects the linkage (wrong calibration, a jam, the open stop) and
it sets the grip force on an object.

| State of a finger | Torque limit (register 48, RAM, written by the HAL) | Setpoint |
|---|---|---|
| free | `torque_limit` (high: speed, and the ceiling) | ramps to the target at `max_speed` |
| blocked | `hold_torque` (low: the force we want) | frozen just past the measured position, in the blocked direction |

- **Blocked** = the finger must move and does not: the setpoint is more than
  `blocked_error` from the measured position, and the measured position changed
  by less than `blocked_motion` over the last `blocked_cycles` cycles. Not the
  lag alone: a slow servo (low torque limit) lags in free motion too.
- **Released** when the command goes to the other side of the finger, or when
  the encoder shows that the finger moves again (the obstacle is gone). The
  full torque returns. The current cannot be the release signal: it is low in
  the hold state on purpose.
- Each finger alone. `/hand/state` stays the measured position.
- Force before the detection is still `torque_limit` for ~0.1 to 0.2 s.
- Current (register 69, unit 6.5 mA) as a better contact signal: not proven. A
  hard push by hand against a holding motor gave only 6.5 to 13 mA, because
  the gear friction carries the load. The case that matters (the MOTOR drives
  into a block) is not measured. Encoder rule first; current as a second input
  of the same detector if it turns out to work.
- Not chosen: the overload protection inside the servo (EEPROM: overload
  torque, protection time, protective torque; protection current). It is a
  trip, the finger goes limp, recovery is unclear, and the values would live in
  the servo and not in `hand_params.yaml`. Possible later as a last backstop.
- Not chosen: force from the distance of the frozen setpoint (`squeeze`). The
  servo gave ~1.3 % drive for each step of error (load 52 at error 4), and
  where that saturates is unknown, so distance is not a reliable force knob.

Files: a pure module `hal/contact.py` (the state logic, no ROS) with tests;
`set_torque_limit(finger, value)` on the backend (nothing in the sim); a few
lines in `hal_node.update()`; `hold_torque` and the `blocked_*` values in
`hand_params.yaml`; a HAL test on the fake servo bus, extended so that a fake
servo can have a mechanical stop. The thresholds need tuning on the hand.

## Calibration

- One-time tool `servo_tool calibrate`, NOT a routine at each start: the
  encoders are absolute, so the values survive a power cycle (they are lost
  only if a horn is mounted again), and a start routine would move a hand that
  a person wears, where "resistance" can be a finger joint.
- Motor-driven, with the SAME blocked detector as the contact stop (one logic,
  two callers): low torque, one finger at a time, drive slowly toward open
  until blocked -> `open_step`.
- **Open side only.** The linkage binds at 84 to 100 deg horn angle, past the
  closed position; driving "until resistance" there can lock it.
  `closed_step = open_step +- max_angle * 4096 / 360` (~830 steps), with
  `max_angle` from `hand_params.yaml`.
- The open direction is per servo (mirrored mounting): a small test motion and
  a "did it open? y/n" question, or a sign in the YAML.
- The tool prints the YAML lines; the person writes them. No hand in the
  exoskeleton during the run.
- Until it exists: `servo_tool jog <id>` by hand, note the open and the closed
  step, type them into `hand_params.yaml` (no rebuild, restart the launch).

## What is built (2026-09-19, fake servo bus only)

- Hazards 1-4 are fixed. The backend no longer enables the torque in its
  constructor. The HAL adopts the first measured pose (NOT clamped), gives the
  motors torque with that pose as the goal, and sweeps a finger that is outside
  its travel into range at the normal speed; the same on the way out of passive
  mode. `servo_tool scan` reports a servo that pings but cannot be read.
- Contact stop as designed: `hal/contact.py` (pure), `set_torque_limit(finger,
  blocked)` on the backend, `servos.hold_torque` and a `contact_stop:` section in
  `hand_params.yaml`. Tests run the HAL on fake servos that move and can have a
  mechanical stop (`test_contact.py`), and `hardware.launch.py` ran end to end
  against them: blocked at the obstacle, low torque, freed by the open command.
- **The calibration is NOT motor-driven towards open, on purpose.** The linkage
  has no open stop before it binds: opening past the CAD pose it runs into its
  own toggle point after 28 deg of horn (thumb, index, pinky) or 33 deg (middle,
  ring) - `open_lock_rad` in `config/linkage.yaml`. "Drive until blocked" would
  find that point, with the pin forces a toggle brings, not the open pose.
  `servo_tool calibrate` is therefore a window where the person sets BOTH ends
  by eye (asked for: no questions, no computed closed position): pick a finger -
  only that one gets torque, and a low one - move it, "Set OPEN", move it, "Set
  CLOSED", Save into `hand_params.yaml`. A span past where the CAD says the
  linkage binds is warned about, not refused. An optional "Test" runs slowly
  between the two positions and stops pushing when the finger is blocked.
  Consequence: `closed_step` is no longer tied to `max_angle`. Normalized 1.0 is
  whatever was set as CLOSED, while the 3D views still draw 1.0 as `max_angle` of
  horn - if the set span differs much, put `span / 651.9` into `max_angle`. If a blocked-based
  open search is wanted later, it has to back off by `open_lock_rad` from the
  blocked point and needs a torque low enough for the toggle.
- The placeholder calibration spanned 1024 steps = 90 deg of horn; middle and
  ring bind at 84 deg. It now spans `max_angle` (836 / 816 steps). It is still a
  placeholder: `open_step: 2048` is a guess.

## Order

1. `hal/contact.py` + tests (the detector and the free/blocked state).
2. HAL integration + `set_torque_limit`, fake-bus test with a mechanical stop.
3. `servo_tool calibrate` on the same detector; fix hazards 3 and 4 on the way.
4. Tune on the hand: `hold_torque`, the `blocked_*` values, then put
   `torque_limit` back up for speed.
