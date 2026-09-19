# htn-2026

Monorepo for the exoskeleton hand.

- `physical_layer/` - everything that touches the hand itself
  - `ros2_ws/` - ROS 2 (Humble) workspace
    - `htn_description` - URDF of the hand, generated from `config/hand_params.yaml`
    - `htn_launch` - `sim.launch.py` and `hardware.launch.py`
    - `htn_control` - hand HAL (sim / serial backends) and keyboard teleop
    - `htn_auto` - autonomous finger control (stub; policy/VLA details live outside the workspace)

## Run

```bash
physical_layer/build.sh      # colcon build, output always lands in physical_layer/ros2_ws
source physical_layer/ros2_ws/install/setup.bash

# simulated hand (Gazebo, headless) + HAL + camera + Foxglove bridge + finger control window
ros2 launch htn_launch sim.launch.py            # gui:=true for the Gazebo window
```

Finger control window: hold a key to move a finger, let go and it holds its
position (window must be focused). Several keys can be held at once.

| finger | thumb | index | middle | ring | pinky |
|---|---|---|---|---|---|
| open  | `Q` | `W` | `E` | `R` | `T` |
| close | `A` | `S` | `D` | `F` | `G` |

Sliders do the same with the mouse, the bars show the measured position.

Below the sliders are buttons for pre-written movements: **poses** (open, fist,
point, peace, thumbs up, pinch, ...) and **sequences** (wave, grab + release,
count). Click one to run it, click it again to go back to open; touching a
finger key takes manual control back. They are plain lists in
`htn_control/htn_control/poses.py` - add an entry there and a button appears.
`teleop:=false` skips the window; `ros2 run htn_control teleop` is a terminal
version with the same keys.

Visualization: open Foxglove, *Open connection* -> `ws://localhost:8765`, add a
**3D** panel (the hand shows up from `/robot_description` + `/tf`) and a **Plot**
panel on `/hand/state.data[0]` ... `[4]`. Or import `physical_layer/foxglove/htn_hand.json`
(Layouts -> Import from file) for the hand model + RealSense color and depth.
`camera:=none` runs without the camera.

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
- `physical_layer/ros2_ws/src/htn_description/config/hand_params.yaml` holds the physical description:
  handedness (currently **left**), palm and finger sizes, masses, angle limits, mount poses, joint physics, and
  servo calibration. The URDF and the HAL both read it; pass
  `params_file:=/path/to/other.yaml` to either launch file to try another hand.
- New hardware = a new `HandBackend` subclass in `htn_control/hal/`, registered
  in `hal/__init__.py`. The serial protocol the firmware must speak is
  documented in `hal/serial_backend.py`.
