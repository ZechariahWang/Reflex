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

`--fps` is the rate of `send_action()`; the camera delivers 15 fps. To stop the
policy and take the hand back with teleop, stop the client: a running policy
overrides every other publisher on `/hand/command`.

The client of lerobot 0.6.1 has no `rename_map` option, and the server replaces
the map of the checkpoint with an empty one. The adapter therefore names its
camera `camera2`, an image key of `smolvla_base`, and no map is used anywhere.
