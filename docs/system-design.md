# System design

Device layout, ROS layout and learned finger control for the exoskeleton hand.
Status: design only, the autonomous part is not implemented. Date of the
discussion: 2026-09-19.

## Device layout

```
        on the wearer                                  on a table
+--------------------------------+            +---------------------------+
| hand                           |            | GPU laptop (8 GB VRAM)    |
|   servos <- USB-C motor driver |            |   LeRobot policy_server   |
|   wrist camera (RGB + depth)   |            |   SmolVLA                 |
|        | USB          | USB    |            |   RobotClient + ExoHand   |
| wearable ROS machine           |  5 GHz     |   no ROS                  |
|   (Pi 5 or small laptop)       |  WiFi      |                           |
|   ROS 2 Humble, rosbridge      | <--ws:9090-|                           |
+--------------------------------+            +---------------------------+
```

- **Hand:** 5 servos behind a USB-C motor driver, and a wrist camera with depth.
  Both connect to the wearable machine over USB.
- **Wearable ROS machine:** runs all ROS nodes. The wearer carries it. It has
  no GPU work, no `lerobot` and no torch.
- **GPU laptop:** runs all the LeRobot parts: `policy_server`, `RobotClient`
  and the `ExoHand` adapter (`lerobot-record` also, during data collection).
  It stays off the body. It needs no ROS, only `roslibpy`.
- **Link:** 5 GHz WiFi hotspot. Bluetooth is too slow for video. An Ethernet
  cable is an option only when the wearer does not move around.
- **Viewing:** a third device can open Foxglove on
  `ws://<wearable-ip>:8765`. It needs no ROS.

Only the rosbridge WebSocket (JSON: `/hand/state`, JPEG frames in, and
`/hand/command` out) and the Foxglove WebSocket cross the network. No DDS
traffic crosses it, so the ROS 2 over WiFi problems (multicast discovery,
fragmented image messages) do not apply. gRPC between `RobotClient` and
`policy_server` stays on localhost of the GPU laptop. See
`specs/policy-link-design.md`.

rosbridge has no authentication: any device on the network can publish
`/hand/command`. Use an own router, a hotspot or a cable, not the venue WiFi.

## ROS layout (wearable machine)

```
camera node --/camera/... images--+
                                  v
                             rosbridge  <--ws:9090-->  ExoHand adapter (GPU laptop)
                                  |  ^
                   /hand/command  v  |  /hand/state
teleop_gui --/hand/command-->    HAL  --USB--> motor driver --> servos
                                  |
                                  +--/hand/state, /joint_states--> foxglove_bridge
```

- `hardware.launch.py` starts `robot_state_publisher`, the HAL (feetech
  backend), `teleop_gui`, the camera node, `foxglove_bridge` and
  `rosbridge_websocket`. The policy link adds no node to this machine.
- The contract does not change: anything that moves the hand publishes
  `/hand/command` (5 values, `0` = open, `1` = closed) and reads `/hand/state`.
  The policy is one more publisher, the same as teleop. The topic is shared
  and the last message wins, so a publisher sends only when it has something
  new; the policy adapter has a deadband for this.
- The HAL clamps and rate-limits (`max_speed`) each command before it reaches
  the servos. This stays below the policy.
- The image topics are also the source for dataset recording and for Foxglove,
  so video and `/hand/state` have timestamps from one clock.

### Wearable machine: Pi 5 or small laptop

| | Pi 5 | Small x86 laptop |
|---|---|---|
| ROS 2 Humble | Needs a container. Ubuntu 22.04 does not boot on a Pi 5. Use distrobox with `ubuntu:22.04` on Raspberry Pi OS or Ubuntu 24.04. | Native, or the same distrobox setup as the dev machine |
| Device access in distrobox | Create the box with `--additional-flags "--group-add keep-groups"` (or `--root`) for `/dev/ttyACM0` and the camera | Same |
| Teleop window | `teleop_gui` needs a display and a keyboard | Built in |
| Power | 5 V / 5 A supply, plus 1-2 W for the camera | Own battery |
| Video encode | No hardware encoder; the `/compressed` topics are JPEG on the CPU, and rosbridge adds base64 per client. Measure the load early. | - |

Start at boot on a Pi: a systemd service that runs
`distrobox enter humble -- <launch command>`. Test it early.

## Policy

**SmolVLA** (0.45B parameters, Apache 2.0, part of
[LeRobot](https://github.com/huggingface/lerobot)), fine-tuned with one constant
instruction.

- **Task:** close when the wearer reaches for an object, hold during transport,
  release when the wearer puts the object down. The wearer cannot move their
  fingers. In operation the servos have torque and are not backdriven; a
  torque-off mode exists only for data collection
  (`specs/data-collection-design.md`).
- **Input:** wrist RGB and depth, and the 5 values of `/hand/state`.
  **Output:** 5 targets for `/hand/command`.
- Inference needs ~2 GB of VRAM. The constant instruction makes the language
  input irrelevant; the reason to use a VLA is the pretrained vision.
- Fallback if SmolVLA generalizes poorly: GR00T N1.6. π0 and π0.5 do not fit.

| Model | Inference VRAM | Fine-tune VRAM |
|---|---|---|
| SmolVLA | ~2 GB | 10-24 GB |
| GR00T N1.6 | ~6 GB | 24 GB+ |
| π0 / π0.5 | 8 GB+ | 22.5 GB+ (LoRA) |

### Inputs

- State and action have 5 values each. SmolVLA pads them to its internal size.
- `smolvla_base` declares three image slots, `observation.images.camera1`,
  `camera2`, `camera3` (top, wrist, side in the pretraining data). Map the
  dataset keys to the slots with `--rename_map`, and mask unused slots with
  `--policy.empty_cameras=N`. Put the wrist RGB in `camera2`.
- Async inference in lerobot 0.6.1 ignores `rename_map`, so the adapter names
  its camera `camera2` directly and no map is used, see
  `specs/policy-link-design.md`.
- **Depth:** record it as a second video stream (color map) and map it to a
  camera slot. The vision encoder has not seen depth images, so unfreeze it for
  that run (`freeze_vision_encoder=false`, `train_expert_only=false`). Option if
  depth does not help as an image: add the median center depth to the state
  vector.

### Inference link

Uses [LeRobot asynchronous inference](https://huggingface.co/docs/lerobot/en/async).
The server computes the next chunk of actions while the client executes the
current one.

- GPU laptop:
  `python -m lerobot.async_inference.policy_server --host=0.0.0.0 --port=8080`.
  The server starts empty; the client names the policy and the checkpoint at
  the first connection.
- Also on the GPU laptop: a `RobotClient` that wraps one small LeRobot `Robot`
  subclass for the hand (`ExoHand`). It reaches the ROS topics through
  rosbridge with `roslibpy`. `get_observation()` returns the latest frame and
  `/hand/state`; `send_action()` publishes to `/hand/command`. The action
  queue is thus off the robot: each command crosses WiFi.
- `lerobot-record` uses the same `Robot` class, so recording and inference
  share keys and camera order.
- Start with `actions_per_chunk` = 10-20 and `chunk_size_threshold` = 0.7 for a
  short reaction time. Check the queue with `--debug_visualize_queue_size=True`.

| Step | Time |
|---|---|
| WiFi, one direction | 2-10 ms, spikes to 50 ms or more |
| Frame age at `get_observation()` | up to 66 ms at 15 fps, plus transit |
| SmolVLA inference | 100-200 ms |

## Training

- Cloud GPU on Lambda. An A10 (24 GB) is sufficient for the default fine-tune;
  use an A100 for the run with the unfrozen vision encoder.
- Lambda deletes the instance storage at termination. Push the checkpoints to
  a private Hugging Face repository (`--policy.repo_id`). The built-in push
  uploads only the final checkpoint, so copy the output folder with `rsync`
  before termination if a run stops early.
- Dataset storage is not decided. The dataset contains video of people; the
  options are a private Hugging Face dataset repository or local files only.
- 20,000 steps take ~4 hours on an A100.
- Train three versions and compare them on held-out objects:
  1. RGB only, frozen vision encoder (default)
  2. RGB and depth, frozen
  3. RGB and depth, unfrozen

## Safety

These stay in the HAL, below the policy and the network. The motor driver has
no firmware of ours, so the HAL is the lowest layer that we control:

- Clamp and rate limit (exists in the HAL).
- Hard limit on force or current.
- Link loss: the HAL keeps the last target with no time limit, so the hand
  finishes its last commanded move and holds. Hold is the chosen action (an
  open drops the object at each WiFi dropout), so the HAL needs no watchdog.
  The adapter stops the client when its data is old.
- An emergency open that the wearer can always reach.

## Open questions

1. **Where the `RobotClient` runs.** Closed, see
   `specs/policy-link-design.md`: on the GPU laptop, through rosbridge. No
   process imports both `rclpy` and `lerobot`, and `htn_auto` is removed.
2. **Depth camera model.** The object is 5-20 cm from a wrist camera at the
   moment of the grasp. A RealSense D435 cannot measure below ~28 cm; a D405
   operates from ~7 cm. On a Pi, `librealsense` needs a source build.
3. **Release signal.** A learned release is a risk (dropped object or trapped
   hand). Recommended for the first version: learned close, explicit release
   input from the wearer (button, voice, or IMU gesture).
4. **Wearable machine.** Pi 5 or small laptop, see the table above.
5. **Wrist IMU.** It gives the "arm stopped" cue directly and helps most with
   the release.
6. **Motor driver protocol.** Closed, see `specs/feetech-hal-design.md`: Feetech ST
   servos on a USB bus adapter, position feedback, no command timeout. Original question: The `SerialBackend` in the HAL speaks an ASCII
   protocol (`S ...` / `P ...` lines) made for our own firmware. A driver board
   has its own protocol, so the HAL needs a backend for it. Check also whether
   the driver has a command timeout and position feedback; if it has no
   timeout, the watchdog must be in the HAL.
7. **Command arbitration.** `/hand/command` is shared and the last message
   wins. A policy that streams at 15-30 Hz overrides teleop and the web
   console while it runs; the only takeover is to stop the client.

## Alternatives considered

- **Pi with no ROS** (MJPEG stream plus the serial port over TCP, all ROS on
  the GPU machine). Simplest, but it puts ROS and the GPU on one machine.
- **ROS nodes on two machines.** ROS 2 over WiFi is unreliable (discovery,
  large messages).
- **`RobotClient` on the wearable machine** (gRPC across WiFi, the action
  queue on the robot). The queue drains through a short dropout, but
  `lerobot` and torch go onto the wearable machine, and one process needs
  both `rclpy` (Python 3.10) and `lerobot`.
- **One laptop for everything.** Rejected: the wearer must not carry the GPU.
- **ACT.** Not used, also not as a baseline: it has no pretrained vision, and
  SmolVLA is the only model that is trained.

## Links

- [LeRobot repository](https://github.com/huggingface/lerobot)
- [Async inference docs](https://huggingface.co/docs/lerobot/en/async),
  [source](https://github.com/huggingface/lerobot/tree/main/src/lerobot/async_inference)
- [SmolVLA docs](https://huggingface.co/docs/lerobot/en/smolvla),
  [base weights](https://huggingface.co/lerobot/smolvla_base)
- [Rename map and empty cameras](https://huggingface.co/docs/lerobot/rename_map)
- [rosbridge protocol](https://github.com/RobotWebTools/rosbridge_suite/blob/ros2/ROSBRIDGE_PROTOCOL.md),
  [roslibpy](https://roslibpy.readthedocs.io/)
- [ACT paper](https://arxiv.org/abs/2304.13705)
