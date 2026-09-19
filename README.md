# htn-2026

Monorepo for the exoskeleton hand.

- `ros2_ws/` - ROS 2 (Humble) workspace
  - `htn_launch` - `sim.launch.py` and `hardware.launch.py`
  - `htn_control` - manual teleop of the fingers
  - `htn_auto` - autonomous finger control (policy/VLA details live outside the workspace)

```bash
cd ros2_ws
colcon build --symlink-install
source install/setup.bash
ros2 launch htn_launch sim.launch.py mode:=teleop       # or mode:=auto
ros2 launch htn_launch hardware.launch.py mode:=teleop
```
# htn-2026
