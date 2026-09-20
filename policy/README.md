# policy

LeRobot side of the learned policy. Everything here runs on the GPU laptop and
reaches the hand through the rosbridge websocket of the ROS machine
(`ws://<ros-ip>:9090`). Design: `../docs/specs/policy-link-design.md`.

`lerobot_robot_exo_hand` is the hand as a LeRobot `Robot` (`--robot.type=exo_hand`).

## Setup

Python >= 3.12 (a requirement of `lerobot`). No ROS.

```bash
cd policy
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]" "lerobot[smolvla,async,training]==0.6.1"   # async = gRPC for the inference loop, training = lerobot-train
python -m pytest            # no rosbridge needed
```

## Smoke check

With `sim.launch.py` or `hardware.launch.py` running on the ROS machine and the
camera plugged in (the sim has no simulated camera):

```bash
python -m lerobot_robot_exo_hand.exo_hand --host <ros-ip>
```

It prints one observation (the state and the shapes of `camera1`, the head
iPhone, and `camera2`, the wrist RealSense), closes the hand, opens it again, and
fails if `/hand/state` does not follow. With no phone: `--head-topic ""`, and
`--robot.head_topic=""` in the commands below.

## The instruction

One constant string, in every episode and at inference, character for character:

    grasp and put down objects, make a peace sign at a person

It is the default of the console's Task field. The model sees the same words in every sample, so
they tell it nothing: WHICH of the two it does, and when, it learns from the cameras in the
episodes. A different string at inference is an input it was never trained on. So the data has to
tell the two apart:

- grasp episodes with people in the background (or every person in view means "peace sign");
- peace sign episodes with one clear cue: the hand up, palm away, a person close and centred;
- idle episodes: a person in view, or an object out of reach, and the hand does nothing;
- every grasp episode is the whole cycle: approach, grasp, hold, put down, release;
- about as many episodes of the one as of the other.

## Data collection: mirror teleop (torque on)

Design: `../docs/specs/mirror-teleop-design.md`. A second person (the controller)
closes a hand in front of a browser webcam, the web console turns it into
`/hand/command`, and the hand moves with the torque on. `exo_hand_command` records
the last `/hand/command` as the action (the measured `/hand/state` until the first
command); the observation state is `/hand/state`. It works with any command source
(mirror, sliders, keys), and refuses a HAL in passive mode. `--robot.passive=true`
stops the robot from publishing each command a second time. No `label.py` step.

In the web console: ARM, Mirror on, calibrate (open hand, fist), match the hand
until the mode is `following`. Nobody arms the sliders in another tab. Then:

```bash
lerobot-record \
    --robot.type=exo_hand --robot.host=<ros-ip> --robot.id=exo --robot.passive=true \
    --teleop.type=exo_hand_command --teleop.host=<ros-ip> --teleop.id=exo \
    --dataset.repo_id=<user>/exo_grasp --dataset.push_to_hub=false \
    --dataset.root=policy/datasets/exo_grasp \
    --dataset.single_task="grasp and put down objects, make a peace sign at a person" \
    --dataset.fps=30 --dataset.num_episodes=50 \
    --dataset.episode_time_s=20 --dataset.reset_time_s=5
```

Right arrow = save the episode, left arrow = record it again, Esc = stop (the keys
may not work on Wayland; `episode_time_s` is the upper limit then).

## Data collection from the web console

The Episodes bar of the console (under the 3D hand) records without LeRobot on the ROS machine:
type a dataset name and the task, **Record**, move the hand (mirror, sliders, keys), **Save** or
**Discard**; **Replay** plays an episode back on the hand and in the camera panels. The episodes are
in `policy/datasets/console/<name>/` in the console's own format
(`application/CONTRACT.md`, Episodes). On the machine that trains:

```bash
python -m lerobot_robot_exo_hand.from_console --root policy/datasets/console/exo_grasp
```

writes `policy/datasets/exo_grasp`, a LeRobot dataset with the same columns as `lerobot-record`
below (`observation.state`, `action` = the last command, `camera1`, `camera2`). Not run against
lerobot yet when it was written: check the first conversion with `lerobot-dataset-viz` or the
replay below.

## Replay of a LeRobot dataset

```bash
python -m lerobot_robot_exo_hand.replay --root policy/datasets/exo_grasp --episode 0 --host <ros-ip>
```

Plays one episode back through rosbridge at the fps it was recorded with: `action` goes to
`/hand/command` (the hand of the sim, or the real one, does what it was told), and the two camera
images go to `/head_camera/color/image_raw/compressed` and `/camera/color/image_raw/compressed`,
so the web console and Foxglove show what the cameras saw next to the moving hand. For that the ROS
side must have NO camera of its own running: `ros2 launch htn_launch sim.launch.py camera:=none`.
With a live camera pass `--no-images` (the hand only). `--what state` sends the measured
`observation.state` instead of the action (what the hand did, not what it was told),
`--speed 0.5` is half speed, `--loop` repeats until Ctrl-C. It commands the hand: on the real one,
clear its surroundings first. The episode is decoded before the first frame goes out, so a slow
video decode is not part of the timing.

## Data collection: backdrive (closed for these servos)

Design: `../docs/specs/data-collection-design.md`. The HAL is in its torque-off
mode, a person moves the fingers, and the encoder positions are the actions.
`exo_hand_leader` reads them from `/hand/state`; `--robot.passive=true` stops
the adapter from publishing them as commands.

First put the HAL in that mode, on the ROS machine: start it with
`ros2 launch htn_launch hardware.launch.py passive:=true`, or switch a running
one with the Backdrive button of the control window / web console, or
`ros2 service call /hand/set_passive std_srvs/srv/SetBool '{data: true}'`.
`/hand/passive` (latched Bool) tells which mode it is in. With the torque on the
fingers do not move and every label is constant, so `exo_hand_leader` refuses to
record unless `/hand/passive` is true (`--teleop.require_passive=false` for a
recording where something else commands the hand). Afterwards switch it off the
same way (`data: false`): the hand then holds the pose the fingers are in.

Then run from the repo root:

```bash
lerobot-record \
    --robot.type=exo_hand --robot.host=<ros-ip> --robot.id=exo --robot.passive=true \
    --teleop.type=exo_hand_leader --teleop.host=<ros-ip> --teleop.id=exo \
    --dataset.repo_id=<user>/exo_grasp_raw --dataset.push_to_hub=false \
    --dataset.root=policy/datasets/exo_grasp_raw \
    --dataset.single_task="grasp and put down objects, make a peace sign at a person" \
    --dataset.fps=15 --dataset.num_episodes=50 \
    --dataset.episode_time_s=20 --dataset.reset_time_s=5

python -m lerobot_robot_exo_hand.label --root=policy/datasets/exo_grasp_raw --k=3 --gain=0.2
```

The second command writes `policy/datasets/exo_grasp_raw_k3_g20`, the dataset
to train on: `action[t] = min(1, state[t+k] * (1 + gain))`. The raw dataset
does not change, so `k` and `gain` can change with no new recording.

`policy/datasets/` is ignored by git and is not a cache: make a copy outside
the repo after each session.

## Training

`lerobot-train` does it; there is no training code of ours. A rental of a Lambda GPU runs it
with no person at the keyboard (next section). By hand, on a machine with a GPU: the Setup
above, then

```bash
lerobot-train \
    --policy.path=lerobot/smolvla_base --policy.device=cuda --policy.push_to_hub=false \
    --dataset.repo_id=<user>/exo_grasp_raw_k3_g20 --dataset.root=<path>/exo_grasp_raw_k3_g20 \
    --batch_size=64 --steps=20000 --save_freq=5000 \
    --output_dir=outputs/train/exo_grasp --wandb.enable=false
```

The checkpoint for the inference loop is
`outputs/train/exo_grasp/checkpoints/last/pretrained_model` (~1.3 GB with the
training state). Copy it off a cloud instance before termination.

Checked on 2026-09-19 with a dry run on a CPU (10 steps, batch 2, the
150-frame test recording): the 5-value state and action need no option and no
model change, the loss goes down, and the checkpoint gives a `(1, 5)` action
from a 5-value state and one `camera2` image. `batch_size`, `steps` and the
`cuda` device are not run. The checkpoint keeps the input list of
`smolvla_base` in its `config.json` (a 6-value state, `camera1`..`camera3`);
the model pads the state to 32 values and skips the cameras that are not
there, so this had no effect in the dry run.

If the log says that `torchcodec` cannot load `libavutil`, lerobot decodes the
video with `pyav`. It works, and it is slower: install an FFmpeg that
`torchcodec` supports on the training machine.

## Training on a rented Lambda GPU

Design: `../docs/specs/lambda-training-design.md`. `lambda/launch.sh` rents one instance, uploads
`policy/`, one dataset, the `exo-trainer` skill and `docs/notes/training/`, and starts Claude Code
(Fable 5.1) there. The agent runs the variants of `docs/notes/training/plan.md`, evaluates each
checkpoint on held-out episodes (`heldout.py`), writes `docs/notes/training/runs/RUN-<UTC>/` and
ends the rental. `lambda/watchdog.sh` on the laptop pulls `policy/outputs/`, `policy/logs/` and the
run notes every 5 minutes and terminates the instance: 30 minutes after the last sign of life, at
`LAMBDA_MAX_HOURS`, or when the agent asks. **Keep the laptop awake and online for the whole
rental: nothing else stops the billing.**

```bash
cp policy/lambda/.env.example policy/lambda/.env   # the keys, the GPU type, LAMBDA_DATASET, the cap
policy/lambda/check_key.sh
policy/lambda/launch.sh --dry-run          # the confirm screen and the capacity, no launch
policy/lambda/launch.sh --smoke-scripts    # ~10 min, no agent: 50 steps on a fake dataset
policy/lambda/launch.sh --smoke            # the agent, two 50-step variants on the fake dataset
policy/lambda/launch.sh                    # the rental of plan.md; then: tmux attach -t htn-train
policy/lambda/check_instance.sh            # what bills now
policy/lambda/terminate.sh                 # stop it by hand
```

A smoke run is good if a `pretrained_model` folder and a `results.jsonl` are on the laptop and
`check_instance.sh` shows no instance. Several recording sessions: merge them into one dataset
before a rental. Delete an episode only with `lerobot-edit-dataset`, never by hand: it numbers the
episodes again. The checkpoints come home without `training_state/` (~1 GB each), so a run does not
resume on another rental. Revoke the `claude setup-token` token after the hackathon.

Tests of the scripts, with no instance and no key:

```bash
for t in policy/lambda/tests/test_*.sh; do bash "$t"; done
```

## Inference loop

Two processes on the GPU laptop. The server stays on localhost; only rosbridge
crosses the network.

```bash
python -m lerobot.async_inference.policy_server --port=8080

python -m lerobot.async_inference.robot_client \
    --robot.type=exo_hand --robot.host=<ros-ip> --robot.id=exo \
    --server_address=localhost:8080 \
    --policy_type=smolvla --pretrained_name_or_path=<checkpoint> \
    --policy_device=cuda \
    --task="grasp and put down objects, make a peace sign at a person" \
    --fps=15 --actions_per_chunk=20 --chunk_size_threshold=0.7 \
    --debug_visualize_queue_size=True
```

`--fps` is the rate of `send_action()`; the camera delivers 15 fps. The HAL must
be active: `ExoHand` raises if it is passive, because a passive HAL ignores
every command. To stop the
policy and take the hand back with teleop, stop the client: a running policy
overrides every other publisher on `/hand/command`.

The client of lerobot 0.6.1 has no `rename_map` option, and the server replaces
the map of the checkpoint with an empty one. The adapter therefore names its
camera `camera2`, an image key of `smolvla_base`, and no map is used anywhere.
