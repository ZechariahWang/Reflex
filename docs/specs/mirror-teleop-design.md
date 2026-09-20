# Mirror teleop: a second person's hand commands the exoskeleton

How the demonstrations are made now that backdrive is not usable
(`data-collection-design.md`, Backdrive result). Status: built on 2026-09-19 and
tested without hardware; the done check below has not run. It replaces the design notes of the same day
(free hand of the wearer, standalone script, OpenCV window).

Scope: data collection only. From the controller's webcam to `/hand/command`,
the panel in the web console, and the teleoperator that puts the commands into a
LeRobot recording. Not in scope: the policy cameras, the recording buttons in
the web console (next spec, "recording console"), training.

## Terms

| Term | Who | Cameras |
|---|---|---|
| **Wearer** | Has the exoskeleton on the LEFT hand, moves the arm | Wrist RealSense, forehead iPhone: the policy cameras, in the dataset |
| **Controller** | Sits at a browser; the curl of their fingers is the command | Laptop webcam: tracking only, **never in the dataset** |

## Decisions

- The controller is a second person. The wearer's own free hand is not used: a
  head camera sees it, and a policy that sees the commanding hand learns to copy
  it and fails at inference, where that hand is absent (causal confusion).
  **The controller's hand stays out of the view of both policy cameras.**
- Either hand of the controller works (no handedness in the maths). One hand in
  the webcam view.
- Record with the torque ON. `action` = the value sent on `/hand/command` (it
  goes past the contact point: `1.0` while the finger stops at `0.6`).
  `observation.state` = `/hand/state`, measured. The difference is the grip
  intent, and the contact stop of the HAL turns it into a constant soft squeeze
  (`hal-safety-design.md`). No relabel with `label.py`; look again after the
  first recording.
- Webcam frames are used for the tracking and dropped. Nothing of them goes to
  ROS or to the dataset.
- Hand tracking: **MediaPipe `HandLandmarker`** (pretrained, CPU, real time),
  **no training of ours**. `mediapipe 1.0.1` has a `py3-none-manylinux_2_28`
  wheel (checked). Not verified: whether 1.0 still has the old `solutions.hands`
  API; the design uses the Tasks API (`HandLandmarker` + a `.task` model file,
  stored in the repo, no download at run time).
- The browser is only a camera. Vision and all logic are Python, in
  `application/backend`.
- Tasks: grasps and different grip types (full grasp, pinch, tripod). The grip
  follows from the object the cameras see (one object -> one grip, always); one
  generic instruction for all episodes.
- One episode: reach with the hand open, grasp, lift, put down, release, move
  away open (~10 to 15 s). Vary object, position and approach; ~50 episodes for
  each object is the start point.
- Episodes end with the keys of `lerobot-record` (right arrow = save, left
  arrow = record again, Esc = stop) and `--dataset.episode_time_s` as the upper
  limit. Not verified: LeRobot reads the keys with `pynput`, which often does not
  work on Wayland; the fallback is the fixed episode time. Buttons in the web
  console are the next spec.

## Data flow

```
controller's browser                 backend (FastAPI, Python)                     ROS
webcam -> JPEG 320x240, 30 fps  -->  decode -> HandLandmarker (world landmarks)
          WS /ws/mirror (binary)     -> curl -> calibration -> filter -> engage -> /hand/command -> HAL
panel  <-- mode, curls, landmarks <--  (JSON on the same socket)

recorder (policy/): teleoperator `exo_hand_command` = last /hand/command  -> dataset `action`
```

One machine or several: every link is a host setting that exists
(`ROSBRIDGE_HOST`, `--robot.host`, the frontend's backend address).

## Backend: `app/mirror/`

Pure parts, each with tests and no camera:

1. **`curl.py`**: 21 world landmarks -> 5 bend angles (radians). The bend of a
   finger is the sum of the angles between successive bones, from 3D vectors:
   index = `angle(0->5, 5->6) + angle(5->6, 6->7) + angle(6->7, 7->8)`; the
   other fingers and the thumb (`0->1->2->3->4`) the same way. World landmarks
   (metres, hand-centred), not image landmarks: a finger that curls towards the
   camera moves mostly in depth. The result does not depend on the position,
   distance or rotation of the hand. The curl of one finger is ONE function, so
   the thumb can change to another measure (thumb tip to pinky base) if the
   bench check below fails.
2. **`calibration.py`**: `curl = clip((bend - open) / (fist - open), 0, 1)` for
   each finger; a capture averages ~0.5 s of bends. A calibration whose `fist -
   open` is too small for a finger is refused.
3. **`one_euro.py`**: a one-euro filter for each finger. Hand tracking jitters
   by some percent; without a filter the labels shake and the policy learns to
   shake. The HAL `max_speed` and the servo acceleration are the second and
   third stage.
4. **`engage.py`**: what is sent.

   | Mode | When | Command |
   |---|---|---|
   | `off` | Mirror switch off, or no calibration | none published |
   | `no_hand` | no landmarks in the frame (no frames at all: nothing is published) | hold the last one |
   | `following` | a hand is seen | the filtered curls |

   A hand that comes back is followed at once. The first build made the
   controller match the held pose first ("wait for a match"); on the bench five
   fingers within 0.15 in one frame was too hard to hit, and it was removed
   (2026-09-19). The cost: the command can jump after a dropout; the one-euro
   filter and the HAL `max_speed` soften it. When the calibration completes the
   held command is the current `/hand/state`, and the console captures the fist
   first and the open hand last, so the first thing the hand does is open.

Impure parts:

5. **`tracker.py`**: `HandLandmarker`, `num_hands=1`, JPEG bytes -> world
   landmarks + image landmarks (for the drawing) or `None`. Runs off the event
   loop (a worker thread); latest frame only, never a queue.
6. **`WS /ws/mirror`** in `main.py`: one client at a time (a second one is closed
   with a reason); the same `Origin` allow-list as the other sockets. It
   publishes through the existing `/hand/command` publisher of `ros_client.py`,
   **only on change** (deadband `command_tolerance`), never on a timer
   (`physical_layer/CLAUDE.md`).
7. **Mock mode** (`MOCK=1`): a synthetic hand that opens and closes, so the
   panel is built and tested with no webcam and no MediaPipe.

Config (env, defaults to tune on the bench): `MIRROR_COMMAND_TOLERANCE=0.01`, one-euro
`MIRROR_MIN_CUTOFF` / `MIRROR_BETA`. `mediapipe` goes into `requirements.txt`.

### `WS /ws/mirror` (to add to `application/CONTRACT.md`)

Client -> server: binary = one JPEG frame; JSON text =
`{"type": "calibrate", "pose": "open" | "fist"}`.

Server -> client, one JSON for each processed frame:

```json
{"mode": "following", "calibrated": true,
 "controller": [0.1, 0.8, 0.8, 0.7, 0.6],
 "command":  [0.1, 0.8, 0.8, 0.7, 0.6],
 "landmarks": [[0.41, 0.63], "... 21 image points, 0..1, or null"]}
```

As built there are two more fields, `capturing` and `error`, for the guided
calibration: `application/CONTRACT.md` is the reference. The measured state is
already in `/ws/state`.

## Frontend

- **Mirror switch** in the command block, usable only while armed, built like
  the Backdrive switch: on = open the webcam and the socket, run the guided
  calibration, lock the sliders and presets (one command source at a time).
  Disarm = off. Off or a lost connection = the hand holds the last command.
- **Guided calibration at every connect**: "fist" -> capture, "open hand" ->
  capture (a button and a shortcut for each). No `following` before it is done.
  Nothing is saved: always right for this person, camera and distance.
- **Mirror panel**: the local webcam video with the skeleton drawn from
  `landmarks`; a mode badge, red border when not `following`, with the hint
  ("put your hand in view"); it takes the place of the
  3D hand while Mirror is on; for each finger three bars:
  **ctl** (controller), **cmd** (sent), **st** (measured). Contact: cmd above st.
- Frames: a canvas at 320x240 -> JPEG -> binary message, 30 fps, skip a frame
  while the socket's buffer is not empty.
- **The webcam needs a secure context**: `localhost` or `https`. A controller on
  another laptop runs the frontend locally against the remote backend
  (`CORS_ORIGINS` has the origin), or the frontend is served over HTTPS.

## Recorder: `exo_hand_command` in `policy/lerobot_robot_exo_hand`

A LeRobot `Teleoperator` whose `get_action()` is the last message on
`/hand/command` (`ExoHandLeader` is the pattern: same features, same freshness
and connection checks, no passive check). Before the first command it returns
`/hand/state`. Record with `--teleop.type=exo_hand_command --robot.passive=true`:
the robot must not publish the command a second time. The saved action can be
one frame (33 ms) behind the sent one. It works with any command source
(sliders, keys, mirror).

Rule for a recording: nobody arms the sliders in another tab.

## Tests (TDD, no camera, no ROS)

- `curl`: synthetic landmarks, straight finger ~0, bent finger = the known sum;
  the same hand translated, scaled and rotated gives the same bends.
- `calibration`: scaling, clipping, refusal of a degenerate range.
- `engage`: off until started; a hand -> `following`; dropout -> hold; return ->
  `following` at once; off -> nothing published.
- Socket with a fake tracker: a second client is refused, publish only on
  change, mock mode.
- `exo_hand_command`: returns the last command, the state before any command,
  stale data raises as in `ExoHandLeader`.
- Frontend: the panel against `MOCK=1`; no test of copy or layout.

## Done check (sim, then the real hand)

1. Sim or fake servos + backend + frontend: arm, Mirror on, calibrate. Open,
   fist and a pinch (thumb + index closed, the others open) show on the 3D hand;
   the controller can hold the thumb at ~0.5. A hand out of the view holds the
   hand; it follows again at once when the hand is back.
2. `lerobot-record` with `exo_hand_command` for two short episodes: the `action`
   column is the mirror's command.
3. Measure the loop rate with everything on one laptop (MediaPipe + camera
   streams + video encoding); below 30 Hz, record at 15 to 20 fps or use two
   machines.

Real hand, same code, only the launch file differs. Before anybody wears it
under mirror control: `servo_tool calibrate --write`, tune `contact_stop:` and
`hold_torque` (`hal-safety-design.md`), a first mirror run with the hand off the
wearer. **Do not change the contact stop after the recording starts**: the
policy learns against it.

## TODO, outside this spec

- Done, `iphone-camera-design.md`: the forehead iPhone is a ROS topic
  (`/head_camera/...`) and the second image key (`camera1`) in `ExoHand`. The
  mirror is the same with one policy camera or two.
- Recording console: episode buttons, shortcuts and recording status in the
  frontend. Starts with a read of the `lerobot==0.6.1` record loop to find the
  hook for the three flags.
