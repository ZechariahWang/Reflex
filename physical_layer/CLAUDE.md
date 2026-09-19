# physical_layer

ROS 2 **Humble** workspace (`ros2_ws/`) for the exoskeleton hand. Gazebo
**Fortress** (`ign gazebo`, via `ros_gz` + `gz_ros2_control`), not Gazebo Classic.

## Build / run

```bash
physical_layer/build.sh            # works from any directory; extra args go to colcon
source physical_layer/ros2_ws/install/setup.bash
ros2 launch htn_launch sim.launch.py        # Gazebo headless + HAL + camera + Foxglove bridge + control window
ros2 launch htn_launch hardware.launch.py serial_port:=/dev/ttyACM0
```

Launch args: `gui:=true` (Gazebo window, sim only), `teleop:=false` (no control
window), `foxglove:=false`, `rosbridge:=false`, `camera:=none`, `color_profile:=640x480x15`,
`depth_profile:=480x270x15`, `params_file:=<yaml>`. Foxglove connects to
`ws://localhost:8765`, rosbridge (JSON websocket for `application/`) listens on
`ws://localhost:9090`; import `foxglove/htn_hand.json` (Layouts -> Import from
file) for hand model + color + depth.

One-time camera setup on a new machine: `sudo apt install
ros-humble-realsense2-camera`, the librealsense udev rules, and
`udev/99-realsense-nolpm.rules` (install steps in the file).

With `--symlink-install`, edits to Python, launch, YAML and xacro files need no
rebuild - just relaunch. Rebuild after adding files, entry points or packages.

## Packages (`ros2_ws/src`)

- `htn_description` - `urdf/hand.urdf.xacro` builds the whole URDF from
  `config/hand_params.yaml` (palm/finger sizes, masses, angle limits, mount
  poses, joint physics, sim mount, servo calibration). Change the hand by
  editing the YAML, not the xacro. Mount poses in the YAML are written for a
  right hand; `handedness: left` (current) mirrors them in the xacro. `sim:=gazebo` pulls in `hand.gazebo.xacro`
  (world mount + ros2_control).
- `htn_launch` - `sim.launch.py`, `hardware.launch.py`, `config/controllers.yaml`,
  `worlds/`. `camera.launch.py` is the camera HAL, included by both (the camera
  is real even when the hand is simulated): it pins the RealSense driver to the
  `/camera/...` topics of the root CLAUDE.md contract. Another camera = another
  node in that file publishing the same topics, selected by `camera:=`.
- `htn_control` - the HAL and manual control:
  - `hal_node.py`: subscribes `/hand/command` (5 x 0..1), clamps, rate-limits
    (`max_speed`), writes to a backend, publishes `/hand/state`.
  - `hal/`: `HandBackend` base class, `SimBackend` (radians ->
    `/hand_position_controller/commands`), `SerialBackend` (servo degrees over
    serial; wire protocol documented in the file - firmware must match it).
    New hardware = new subclass registered in `hal/__init__.py`.
  - `teleop_gui.py` (tkinter window, started by the launch files): hold-to-move,
    open/close key pairs `Q/A W/S E/D R/F T/G` = thumb..pinky; releasing holds
    position. Key auto-repeat arrives as release+press pairs, hence the
    release debounce. `teleop.py` is the terminal version (same keys, steps per
    repeated character; needs its own TTY so it is never launched).
  - `poses.py`: pre-written movements - `POSES` (name -> 5 normalized values)
    and `SEQUENCES` (list of (pose, seconds)). The control window builds one
    toggle button per entry; reuse these from `htn_auto` rather than redefining.
  - `hand_config.py`: `FINGERS` order and the YAML loader.
- `htn_auto` - stub for autonomous control. Must only talk to `/hand/command` /
  `/hand/state`; policy/VLA code lives outside this workspace.

## Gotchas

- **URDF visuals are boxes only, main body first.** The web viewer in
  `application/` restyles every box, builds the ghost hand from them and reads
  each fingertip off the finger link's *first* box. Cylinders/spheres/meshes
  would show up as solid lumps in the ghost overlay. Decorative parts go through
  the `vbox` macro; colours live under `appearance:` in `hand_params.yaml`.
  Collisions and inertia stay the plain palm plate / finger box - looks never
  change physics.

- **DART joint limits**: in Gazebo a joint resting exactly on its limit ignores
  velocity commands and sticks forever. `hand.urdf.xacro` therefore widens the
  hard limits by `limit_margin` in sim only. Don't remove it, and don't command
  outside `[min_angle, max_angle]`.
- **Stale Gazebo**: Ctrl-C on a launch can leave `ign gazebo` alive; the next
  launch then fails with `Failed to configure controller` / duplicate nodes.
  Fix: `pkill -9 -f "ign gazebo"`.
- **Camera up but 0 Hz**: topics exist, nothing arrives, log repeats `Frames
  didn't arrived within 5 seconds`. On a USB 2 link that is USB link power
  management stalling the video transfers - not the cable, driver or firmware.
  `udev/99-realsense-nolpm.rules` fixes it; the setting is lost on every replug
  (and the camera re-enumerates by itself now and then), so install the rule
  rather than echoing into sysfs. Check: `cat
  /sys/bus/usb/devices/<port>/power/usb2_hardware_lpm` must say `disabled`.
- **Camera profiles**: the defaults (640x480 color + 480x270 depth, 15 fps) run
  at a full 15 Hz on USB 2. Depth and infrared share one sensor and must use
  the same resolution, which is why `camera.launch.py` turns infrared off.
- **rosbridge throttling**: a rosbridge subscription with `throttle_rate` but no
  `queue_length` silently drops to ~1.6 Hz. Always pass `queue_length=1` too.
- **Measuring camera rates**: `ros2 topic hz` on an `image_raw` topic reports
  ~5 Hz because the Python tool cannot keep up with the images. Measure the
  matching `camera_info` topic instead (one tiny message per frame).
- Joint names are `<finger>_joint`, links `<finger>_finger`, root `base_link`
  (`world` exists only in sim).
- Only the HAL's sim backend may publish to `/hand_position_controller/commands`.
- A ROS package must never be called `launch` (shadows the `launch` Python
  module) - hence the `htn_` prefix everywhere.

## Testing without a GUI

```bash
ros2 topic pub --once /hand/command std_msgs/msg/Float64MultiArray "{data: [0, 1, 1, 0, 0]}"
ros2 topic echo /hand/state --once
ros2 control list_controllers      # both must be active
```

The serial backend can be tested without hardware by pointing `serial_port` at a
pty and reading the `S ...` lines it writes.
