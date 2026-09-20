# Contact stop: a block that stays, and a sign of it in the console

Status: design, agreed in the discussion of 2026-09-20. Nothing of it is built. It changes the
"Released" rule of `hal-safety-design.md` and adds one topic.

## The problem

On the hand the contact stop seems to do nothing: a person can resist a finger through a whole
move and it never goes soft.

It does trigger. It lets go again one cycle later. A probe log of the index finger (a close at
probe speed 2.0, `torque_limit` 600, a person resisting the whole move; commit `6447865`,
`free.csv`), replayed through `hal/contact.py`:

```
0.19 s  110 mA  excess  10
0.22 s  130 mA  excess  40
0.24 s  169 mA  excess 109
0.26 s  221 mA  -> blocked
0.28 s  247 mA  -> free
0.30 s  286 mA  -> blocked
0.32 s  254 mA  -> free        ... and so on to the end of the move
```

The cause is the release rule "the finger moves again": more than `hold_lead / 2` (0.015 of the
travel) past the point where it got blocked. A finger at speed covers 0.04 of the travel in one
cycle, so its own momentum frees it in the next cycle. The servo gets `hold_torque` for 20 ms
and the full `torque_limit` again.

The replay uses positions recorded at the full torque. On the hand one cycle of low torque slows
the finger a little; 20 ms is not expected to stop it. Not measured.

A second fault in the same place: the hold setpoint is frozen at the blocked position +
`hold_lead` (0.03). A finger that coasts past it has the setpoint BEHIND it, and the servo pulls
it back, off the object.

## What the logs say about the current

From the same two logs (`free.csv`, `trial.csv`), all moves at the same constant speed of 32 to
33 steps per cycle:

| Move | Load (drive level, 0..1000) | Current at constant speed |
|---|---|---|
| index close, resisted by hand | 590 | 234 to 292 mA |
| index open, free | 465 | 52 to 72 mA |
| other finger close, free | 468 | 46 to 65 mA |

- The current tells a free move from a resisted one by a factor of about 4. Free motion stays
  below 91 mA, start peaks included. `blocked_current` 100 is right above that: the threshold is
  not the problem.
- The finger kept the full commanded speed while resisted: the servo raised its drive level and
  pushed through. So "slower than commanded" does not show a soft resistance; the current does.
- `hal-safety-design.md` says the index draws up to 290 mA on a FREE close and trips on every
  close. That number is from a resisted move. The index needs no threshold of its own.
- The finger needs about 0.32 s to reach its speed (the HAL's ramp is 0.07 s), and the current
  hardly drops after it. A higher threshold while the setpoint accelerates gains little.

Valid near probe speed 2.0 and `torque_limit` 600 only. The HAL runs at `max_speed` 4.0 and
`torque_limit` is 700 now: the free current there is not known.

## Design

### Detector (`hal/contact.py`)

| | Now | New |
|---|---|---|
| Hold setpoint while blocked | blocked position + `hold_lead`, frozen | furthest position reached in the blocked direction + `hold_lead`: it follows the finger forward and never goes back |
| Release by motion | more than `hold_lead / 2` past the blocked position | more than `release_travel` past the blocked position |
| Release by command | the target is on the other side of the finger | the same |

- The servo always pushes toward the object with `hold_torque`; it never pulls a finger back
  that coasted or that squeezes an object that gives way.
- `release_travel` counts from the position where the finger GOT blocked, not from the point
  that follows the finger: a finger that goes on and on is free again after that distance,
  whatever its speed.
- `release_travel: 0.15` in `contact_stop:` of `hand_params.yaml`, next to `hold_lead`. A
  tuning value: the coast after the torque drops is estimated at 0.04 to 0.08 of the travel,
  not measured.
- Nothing else changes: how a finger gets blocked (the summed excess current, the encoder
  rule), the thresholds, `reset()`.

### Topic `/hand/blocked`

`std_msgs/Float64MultiArray`, 5 values in finger order, `1` = blocked, `0` = free, latched like
`/hand/passive`. The HAL publishes it at the start (all 0) and whenever a finger changes state.
A float array, not a byte array: rosbridge hands it over as a plain JSON list, like the other
hand topics. A new entry in "Contracts that cross folders" of the root `CLAUDE.md`.

The sim never publishes a 1: `SimBackend` has no torque limit, so the HAL makes no detectors.

### Web console

- Backend: `blocked` (5 booleans) in the `/ws/state` JSON next to `passive`, from the topic. All
  false until the first message, and in the mock. `application/CONTRACT.md` gets the field.
- 3D view: the contact pad of a blocked finger, on the MEASURED hand, takes the accent colour
  (`SIGNAL` in `hand-model.ts`). Nothing else changes: a blocked finger is a normal state of a
  grasp, not a fault, and the sign must be subtle.
- Telemetry block: the finger's row in the command block takes the accent colour.
- Live state only, no history. A block shorter than one state message is not seen.

## Not in this work

- `max_speed` stays a launch argument. The logs say the servo is near its limit at about 2.0
  travels/s: a higher `max_speed` does not make the real finger faster and raises the free
  current, against the contact stop. Decide after the tests on the hand.
- No expected-speed model, no threshold per finger or per direction, no threshold that depends
  on the acceleration. The logs give no reason for them.
- No switch for a movement to turn the stop off.

## Tests

- `test_contact.py`: rows of the resisted log, inline. The finger gets blocked and STAYS blocked
  to the end of the move (now: it flaps). While blocked, the hold setpoint is never behind the
  finger. A blocked finger that then travels more than `release_travel` is free. The existing
  tests keep passing (release by command, the encoder rule).
- HAL on the fake servo bus: `/hand/blocked` says 1 for a finger driven against a stop, 0 after
  the open command.
- Backend: a `/hand/blocked` message shows up as `blocked` in the state JSON.
- Frontend: no test, the change is a colour.

## On the hand, after the build

1. Resist a finger by hand: ONE `blocked` line in the HAL log and the pad lights, until the
   finger is let go and has moved on, or the command opens it. Many blocked / free pairs = the
   coast is longer than `release_travel`.
2. Free moves of every finger at `max_speed` 4.0: no block. A block here = the free current at
   this speed is above `blocked_current`; read the mA in the log line, then raise it or lower
   `max_speed`.
3. Hot cross buns on the keys, and a grasp of the bottle. Tune `hold_torque`, `blocked_current`
   and `release_travel` from what the log shows.

## Risks

- A false stop makes the finger crawl on `hold_torque` for 0.15 of the travel before it is free
  again. At 4.0 / 700 false stops are likely until step 2 is done.
- An object that gives way more than `release_travel` (a sponge) gets pulses: full torque,
  blocked, full torque.
- `hold_torque` 60 may be too little to press a piano key down once the stop really holds. Until
  now the tune ran with a stop that did not hold.
- If the coast is longer than 0.15, the flapping is back, slower. The pad then flickers.
