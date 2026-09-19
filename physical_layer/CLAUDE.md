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
window), `foxglove:=false`, `rosbridge:=false`, `passive:=true` (hardware only:
start with the torque off for a recording session), `camera:=none`, `color_profile:=640x480x15`,
`depth_profile:=480x270x15`, `params_file:=<yaml>`, `require_all_servos:=false`
(hardware only: bench test with fewer than 5 servos). Foxglove connects to
`ws://localhost:8765`, rosbridge (JSON websocket for `application/`) listens on
`ws://localhost:9090`; import `foxglove/htn_hand.json` (Layouts -> Import from
file) for hand model + color + depth.

One-time camera setup on a new machine: `sudo apt install
ros-humble-realsense2-camera`, the librealsense udev rules, and
`udev/99-realsense-nolpm.rules` (install steps in the file).

With `--symlink-install`, edits to Python, launch, YAML and xacro files need no
rebuild - just relaunch. Rebuild after adding files, entry points or packages.

## Packages (`ros2_ws/src`)

- `htn_description` - the hand as built, from the Fusion CAD export.
  `tools/cad_to_linkage.py <export folder>` generates `meshes/` (decimated STL,
  mm, CAD assembly frame) and `config/linkage.yaml`: the export only contains
  the joints somebody defined in Fusion (2 of ~50), so the tool finds the
  pivots from the pin holes parts share. Every finger is the same 1-DOF chain
  of three four-bars (horn - pushrod - triangle - ternary bar - adapter + pad,
  with a long link and a binary bar; diagram in the tool). `urdf/hand.urdf.xacro`
  builds the URDF from that plus `config/hand_params.yaml` (limits, masses,
  colours, sim mount, servo calibration - what a person decides).
  - `<finger>_joint` is the SERVO HORN, 0 = open = CAD pose, positive closes,
    `max_angle` = horn angle for a 90 deg curl of the contact pad (~72-74 deg);
    the linkage binds at 84-100 deg (`lock_rad`). `<finger>_finger` is the
    adapter + contact pad. `base_link` is the CAD frame: fingers along +Y,
    curling to -Z, thumb on +X (a left hand).
  - URDF is a tree, the linkage has loops: each part hangs on one pivot, and the
    six passive joints per finger (`<finger>_{rod,triangle,ternary,long,binary,adapter}_joint`)
    are published by `htn_control`'s `linkage_publisher` from the horn angles
    (`htn_control/linkage.py`, pure maths; `test_linkage.py` checks on the
    generated URDF that every loop closes to < 0.05 mm).
  - `sim:=gazebo` pulls in `hand.gazebo.xacro` (world mount + ros2_control).
    Gazebo cannot close loops, so `sim.launch.py` spawns `parts:=horns` (base +
    horns, marker cubes) while robot_state_publisher gets the full description.
- `htn_launch` - `sim.launch.py`, `hardware.launch.py`, `config/controllers.yaml`,
  `worlds/`. `camera.launch.py` is the camera HAL, included by both (the camera
  is real even when the hand is simulated): it pins the RealSense driver to the
  `/camera/...` topics of the root CLAUDE.md contract. Another camera = another
  node in that file publishing the same topics, selected by `camera:=`.
- `htn_control` - the HAL and manual control:
  - `hal_node.py`: subscribes `/hand/command` (5 x 0..1), clamps, rate-limits
    (`max_speed`), writes to a backend, publishes `/hand/state`. Passive
    (backdrive) mode - service `/hand/set_passive`, latched `/hand/passive`,
    launch arg `passive:=true`, button in the control window and the web
    console: torque off, commands ignored, state still read. While passive,
    `setpoint = target = measured`, so leaving it holds the current pose; the
    backend gets `set_torque(True, hold=pose)` and must write the goal BEFORE
    the torque (a servo that gets torque with a stale goal drives there at once).
  - `hal/`: `HandBackend` base class, `SimBackend` (radians ->
    `/hand_position_controller/commands`), `FeetechBackend` (Feetech ST bus servos on
    a USB bus adapter, no MCU; `hal/feetech.py` is the wire protocol, no ROS in
    it; design in `docs/specs/feetech-hal-design.md`).
    New hardware = new subclass registered in `hal/__init__.py`.
  - `teleop_gui.py` (tkinter window, started by the launch files): hold-to-move,
    open/close key pairs `Q/A W/S E/D R/F T/G` = thumb..pinky; releasing holds
    position. Key auto-repeat arrives as release+press pairs, hence the
    release debounce. `teleop.py` is the terminal version (same keys, steps per
    repeated character; needs its own TTY so it is never launched).
  - `poses.py`: pre-written movements - `POSES` (name -> 5 normalized values)
    and `SEQUENCES` (list of (pose, seconds)). The control window builds one
    toggle button per entry.
  - `hand_config.py`: `FINGERS` order and the YAML loader.

The learned policy is not in this workspace. It lives in `policy/` at the repo
root and reaches `/hand/command`, `/hand/state` and the camera topics through
rosbridge, see `docs/specs/policy-link-design.md`.

## Gotchas

- **What the web viewer reads off the URDF**: material NAMES pick the look
  (`body servo finger accent pad wearer`, see `hand-model.ts`), links called
  `<finger>_...` belong to that finger (ghost, per-finger fade), and the `pad`
  mesh of `<finger>_finger` is where the fingertip label sits. Keep those when
  editing the xacro. `wearer` is the CAD's mannequin hand: a static reference,
  drawn faint, ignored when framing the camera.
- **New CAD export**: rerun `tools/cad_to_linkage.py` (needs numpy, trimesh,
  fast-simplification, scipy, networkx), then regenerate the web mock:
  `xacro urdf/hand.urdf.xacro > application/backend/mock/hand.urdf`. If the
  closed angles changed, copy `closed_rad` into `max_angle` in hand_params.yaml.
  The real servo calibration (`servos.*_step`) must be redone on hardware: step
  values now mean horn angles of this linkage.

- **DART joint limits**: in Gazebo a joint resting exactly on its limit ignores
  velocity commands and sticks forever. `hand.urdf.xacro` therefore widens the
  hard limits by `limit_margin` in sim only. Don't remove it, and don't command
  outside `[min_angle, max_angle]`.
- **Stale install of a removed package**: after a pull that deletes a package
  (`htn_auto` went this way), `install/<pkg>` and `build/<pkg>` stay behind and
  `ros2 launch` dies with `package '<pkg>' not found`. Delete both folders (and
  the leftover `src/<pkg>/__pycache__`), then rebuild.
- **Stale Gazebo**: Ctrl-C reaches the shell that started `ign gazebo`, not
  always the server behind it. A survivor poisons the next launch: the hand is
  spawned twice over, `spawner_joint_state_broadcaster` hangs, no `/clock`, and
  the HAL (sim time) freezes - commands go out (the web console's orange ghost
  moves) but the measured hand never does. `sim.launch.py` now kills its own
  Gazebo on shutdown and refuses to start next to another server in the same
  `IGN_PARTITION`, printing the `kill -9 <pids>` to run. Symptom check: `ros2
  node list --no-daemon` shows `/gz_ros2_control` twice and no
  `/controller_manager`.
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
- `/hand/command` is **shared** (control window, web app and the policy adapter
  in `policy/`, both via rosbridge). Publish only when you have something new to say - never stream
  your current target on a timer, or you silently override everyone else. The
  control window adopts other publishers' commands into its sliders.
- A ROS package must never be called `launch` (shadows the `launch` Python
  module) - hence the `htn_` prefix everywhere.

## Testing while someone else has the sim running

Never `pkill` Gazebo / HAL processes and never start a second sim in the default
ROS domain - the user (or `application/dev.sh`) often has one running. Test in
isolation and kill only your own launch's children:

```bash
export ROS_DOMAIN_ID=77 IGN_PARTITION=claude_test
ros2 launch htn_launch sim.launch.py teleop:=false foxglove:=false rosbridge:=false
```

If Gazebo dies, `sim.launch.py` shuts the whole launch down on purpose: the HAL
runs on sim time, so without Gazebo it freezes silently and the control window
looks alive while nothing moves.

## Testing without a GUI

```bash
ros2 topic pub --once /hand/command std_msgs/msg/Float64MultiArray "{data: [0, 1, 1, 0, 0]}"
ros2 topic echo /hand/state --once
ros2 control list_controllers      # both must be active
```

The Feetech protocol has tests with a fake servo bus on a pty (no hardware):
`python3 -m pytest ros2_ws/src/htn_control/test` with ROS sourced. Servo setup:
`ros2 run htn_control servo_tool scan | set-id <old> <new> | jog <id>`.
