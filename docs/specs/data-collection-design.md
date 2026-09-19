# Data collection: demonstrations from backdriven fingers

How the demonstrations for SmolVLA are recorded and
labelled. Status: implemented; record and
label run end to end without hardware, not yet against the hand. Date: 2026-09-19. This closes
"the data collection method" of `policy-link-design.md` (Scope, Out).

## Decisions

- Backdrive is a mode for data collection only. During a demonstration the
  torque is off, a person moves the fingers, and the encoders give the motion.
  In operation the servos have torque and the policy moves the fingers. There is no
  second input device and no new topic: the recorder needs only `/hand/state`
  and the camera.
- The label comes from the encoders: the action at frame `t` is the state at
  frame `t + k`, stretched by a grip gain (see `label.py`).
- `lerobot-record` writes the dataset (LeRobotDataset: video, state, action).
  There is no storage format of ours. SmolVLA trains on it directly.
- The recording holds the raw encoder values as the action. The shift and the
  grip gain are applied offline, so `k` and the gain can change with no new
  recording.
- The hand gets no commands during a recording.
- The datasets are stored in `policy/datasets/` on the GPU laptop, a folder
  that git ignores. Nothing is stored on the wearable machine.

## Scope

In: a LeRobot `Teleoperator` that returns `/hand/state`, a `passive` switch on
`ExoHand`, the offline label script, their tests, the README commands, the
`.gitignore` entry for `policy/datasets/`.

Out:
- The HAL passive mode (torque off, `/hand/state` still published). **Built**
  (2026-09-19): service `/hand/set_passive`, latched `/hand/passive`, launch arg
  `passive:=true`, toggles in the control window and the web console; see
  `physical_layer/CLAUDE.md`. Leaving the mode holds the measured pose and
  publishes it once on `/hand/command`, so the "hand jumps when the torque comes
  back" row below no longer applies to the HAL itself. The recorder depends
  only on `/hand/state`.
- Depth (RGB only, as in `policy-link-design.md`).
- Force control. The HAL does position control; the only force value is
  `servos.torque_limit` in `hand_params.yaml`.
- Training, dataset hosting (open question in `../system-design.md`), the
  release signal.

## Data flow

```
wearable ROS machine                              GPU laptop
  HAL (torque off) --/hand/state-----+                   +--> ExoHand (passive)  --observation--+
  camera --/camera/color/.../compressed--> rosbridge ==ws:9090==                                +--> lerobot-record --> dataset
                                                         +--> ExoHandLeader     --action-------+          |
                                                                                              label script (offline)
                                                                                                          |
                                                                                                   training dataset
```

## Components

### `ExoHandLeader` - the teleoperator

In the package `lerobot_robot_exo_hand` (no second distribution):
`config_exo_hand_leader.py` has `ExoHandLeaderConfig`, registered as
`exo_hand_leader`; `exo_hand_leader.py` has `ExoHandLeader`. `__init__.py`
imports the two. lerobot imports the package because of its
`lerobot_robot_` name, and it finds the class from the config name without
`Config` in `config_x` -> `x` (`make_device_from_device_class`).

- Config: `host`, `port = 9090`, `max_age_s = 0.3`, `connect_timeout_s = 10`.
- `connect()`: own `roslibpy.Ros`, subscribes to `/hand/state` with
  `queue_length=1`, waits for the first message. The record loop of lerobot
  0.6.1 gives the observation to the teleoperator only for one robot type
  (`unitree_g1`), so the teleoperator cannot take the state from `ExoHand` and
  needs its own connection.
- `get_action()`: the latest state as `thumb.pos` .. `pinky.pos`, the keys of
  `ExoHand.action_features`. Raises `ConnectionError` if the state is older
  than `max_age_s`, as `ExoHand.get_observation()` does.
- `action_features`: the 5 keys, float. `feedback_features`: empty.
  `send_feedback`, `calibrate`, `configure`: nothing.
- It reuses `KEYS`, `is_fresh` and `to_observation`-style helpers of
  `convert.py`. No lerobot import in the pure parts.

### `passive` on `ExoHandConfig`

`passive: bool = False`. If it is true, `send_action()` publishes nothing and
returns the action. `lerobot-record` calls `send_action()` with each
teleoperator action; without the switch the adapter publishes the encoder
positions as commands, and the hand jumps to the last one when the torque
comes back. The dataset is not affected: lerobot stores the teleoperator
action, not the return value of `send_action()`.

### `label.py` - the offline label script

Pure function, no lerobot import:

```
label(states: N x 5, k, gain) -> N x 5
  out[t] = min(1, states[min(t + k, N - 1)] * (1 + gain))
```

- `k` (frames, default 3 = 0.2 s at 15 fps): without the shift, the action is
  equal to the state in the same frame, and the policy learns to copy its
  input. The hand then does not move. The last `k` frames of an episode use
  the last state.
- `gain` (default 0.2): backdriven fingers stop at the surface of the object,
  so the raw label is the contact position. A position servo at its target
  applies almost no force, and the object slips. The gain puts the target past
  the contact, and `torque_limit` then sets the grip force. A proportional
  gain keeps open at `0`; a constant offset does not let the hand open fully.
- The command-line part reads a recorded dataset, applies `label` for each
  episode to the `action` column (from `observation.state`, not from the old
  action, so it can run again with other values), and writes a new dataset
  (`<root>_k3_g20`). The raw dataset stays as it is. The whole folder is
  copied (the videos are not encoded again), the `action` column of the
  parquet files is written again, and `recompute_stats` of lerobot makes a new
  `meta/stats.json`, which the training uses for normalization.
- Both values are tuning knobs. `k` and `gain` go in the name of the output
  dataset, so a checkpoint is traceable to its labels.

### README

```bash
lerobot-record \
    --robot.type=exo_hand --robot.host=<ros-ip> --robot.id=exo --robot.passive=true \
    --teleop.type=exo_hand_leader --teleop.host=<ros-ip> --teleop.id=exo \
    --dataset.repo_id=<user>/exo_grasp_raw --dataset.push_to_hub=false \
    --dataset.root=policy/datasets/exo_grasp_raw \
    --dataset.single_task="<the constant instruction>" \
    --dataset.fps=15 --dataset.num_episodes=50 \
    --dataset.episode_time_s=20 --dataset.reset_time_s=5

python -m lerobot_robot_exo_hand.label --root=policy/datasets/exo_grasp_raw --k=3 --gain=0.2
```

The commands run from the repo root. In lerobot 0.6.1 `root` is the folder of
the dataset itself, not a parent folder, so each dataset has its own `root`.
The label script writes `policy/datasets/exo_grasp_raw_k3_g20`.

### Storage

`policy/datasets/` is in `.gitignore`: the video shows people, and the files
are large for git. The folder is not a cache. The demonstrations cannot be
made again without a new recording session, and `git clean -fdx` deletes
ignored folders: make a copy outside the repo after each session. The default
of lerobot (`~/.cache/huggingface/lerobot/`) is not used, because a cache
clean-up can delete it.

A dataset layout: `data/` (parquet: state, action, timestamps), `videos/`
(MP4), `meta/` (features, episode index, statistics). ~100 episodes at
640x480 and 15 fps are some hundreds of MB.

The transfer to the training machine is open: `rsync` of the folder, or a
private Hugging Face dataset repository.

`push_to_hub=false` until the dataset storage question is closed: the video
shows people.

## Recording protocol

- 50 to 100 episodes for one task, 10 to 20 s each: approach, grasp, hold,
  release. Piano is a second task with its own episodes and instruction.
- Change the object position, the approach angle, the light and the
  background between episodes.
- Include episodes where the hand comes near the object and does not grasp.
  Without them the policy learns "object in view = close".
- Before the first session: backdrive one finger through its full range and
  compare `/hand/state` with the motion. Gear friction can make the motion
  unnatural.

## Failure behaviour

| Event | Result |
|---|---|
| WiFi drops or the camera stops | `get_observation()` or `get_action()` raises after `max_age_s`; `lerobot-record` stops. Record the episode again. |
| Torque is on during a recording | The fingers do not move, the labels are constant. `passive` prevents commands from the recorder; other publishers (teleop, web console) must be idle. |
| `passive` is not set | The adapter publishes encoder positions to `/hand/command`. No effect while the torque is off; the hand jumps when the torque comes back. |

## Tests

Plain `pytest`, no rosbridge:

- `label`: shift by `k`; the last `k` rows hold the last state; `0` stays `0`;
  the result is never more than `1`; `k = 0, gain = 0` is the identity.
- `ExoHandLeader.get_action()`: the keys are equal to
  `ExoHand.action_features`; it raises with no state and with an old state
  (callbacks fed directly, as in `test_exo_hand.py`).
- `ExoHand` with `passive`: `send_action()` publishes nothing.

Success criterion for the full path: a 2-episode recording against the real
hand, then `label`, then a load of the output with `LeRobotDataset` that shows
`action[t] == min(1, state[t+3] * 1.2)`.

## Risks

1. Grip force is indirect (gain + `torque_limit`). One value for all objects
   is possibly not sufficient; bottle and piano possibly need different
   limits.
2. Distribution shift: a person moves the fingers in the recording, the servos
   move them in inference. The speed profile is different. The shift and the
   action chunks decrease the effect but do not remove it.
3. The friction of backdriven gears (see Recording protocol).

## Not verified

- The recording against the real hand in passive mode. On 2026-09-19 the
  record and label commands ran end to end against the HAL node with the sim
  backend, rosbridge and a fake camera (2 episodes, 150 frames, AV1 video):
  `action[t] == min(1, state[t+3] * 1.2)` holds in each episode. The run found
  that `lerobot-record` reads `robot.cameras`; `ExoHand` has it since then.
- The raw action and the state of one frame differ by up to one sample (0.04
  in the test), because the robot and the leader have separate connections.
  The labels come from `observation.state`, so this has no effect on them.
