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
uv pip install -e ".[dev]" "lerobot[smolvla,async]==0.6.1"   # async = gRPC for the inference loop
python -m pytest            # no rosbridge needed
```

## Smoke check

With `sim.launch.py` or `hardware.launch.py` running on the ROS machine and the
camera plugged in (the sim has no simulated camera):

```bash
python -m lerobot_robot_exo_hand.exo_hand --host <ros-ip>
```

It prints one observation, closes the hand, opens it again, and fails if
`/hand/state` does not follow.

## Data collection

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
    --dataset.single_task="<the constant instruction>" \
    --dataset.fps=15 --dataset.num_episodes=50 \
    --dataset.episode_time_s=20 --dataset.reset_time_s=5

python -m lerobot_robot_exo_hand.label --root=policy/datasets/exo_grasp_raw --k=3 --gain=0.2
```

The second command writes `policy/datasets/exo_grasp_raw_k3_g20`, the dataset
to train on: `action[t] = min(1, state[t+k] * (1 + gain))`. The raw dataset
does not change, so `k` and `gain` can change with no new recording.

`policy/datasets/` is ignored by git and is not a cache: make a copy outside
the repo after each session.

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
    --task="<the constant instruction of the dataset>" \
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
