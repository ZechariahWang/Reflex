# htn-2026

Monorepo for the exoskeleton hand.

- `ros2_ws/` - ROS 2 (Humble) workspace
  - `htn_description` - URDF of the hand, generated from `config/hand_params.yaml`
  - `htn_launch` - `sim.launch.py` and `hardware.launch.py`
  - `htn_control` - hand HAL (sim / serial backends) and keyboard teleop
  - `htn_auto` - autonomous finger control (stub; policy/VLA details live outside the workspace)

## Run

```bash
cd ros2_ws
colcon build --symlink-install
source install/setup.bash

# simulated hand (Gazebo, headless) + HAL + Foxglove bridge + finger control window
ros2 launch htn_launch sim.launch.py            # gui:=true for the Gazebo window
```

Finger control window: one slider per finger plus a bar showing the measured
position. With the window focused, `1 2 3 4 5` toggle thumb / index / middle /
ring / pinky, `-` / `=` nudge the last selected finger, `o` / `c` open / close
all. `teleop:=false` skips the window; `ros2 run htn_control teleop` is the same
thing in a terminal.

Visualization: open Foxglove, *Open connection* -> `ws://localhost:8765`, add a
**3D** panel (the hand shows up from `/robot_description` + `/tf`) and a **Plot**
panel on `/hand/state.data[0]` ... `[4]`.

Real hand: `ros2 launch htn_launch hardware.launch.py serial_port:=/dev/ttyACM0`,
same control window.

## How it fits together

```
teleop / auto --/hand/command--> HAL --+-- sim backend    -> ros2_control -> Gazebo
               (5 x 0..1)         |    +-- serial backend -> microcontroller -> servos
                                  +--/hand/state-->
```

- Everything above the HAL speaks normalized finger positions in
  thumb, index, middle, ring, pinky order: `0` = open, `1` = closed (each finger
  is 1 DOF). The HAL clamps and rate-limits (`max_speed`) before anything moves.
- `htn_description/config/hand_params.yaml` holds the physical description:
  palm and finger sizes, masses, angle limits, mount poses, joint physics, and
  servo calibration. The URDF and the HAL both read it; pass
  `params_file:=/path/to/other.yaml` to either launch file to try another hand.
- New hardware = a new `HandBackend` subclass in `htn_control/hal/`, registered
  in `hal/__init__.py`. The serial protocol the firmware must speak is
  documented in `hal/serial_backend.py`.
