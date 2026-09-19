#!/usr/bin/env bash
# colcon drops build/ install/ log/ into whatever directory it is run from.
# Build through this script (from anywhere) so they always land in ros2_ws/.
# Extra arguments go to colcon, e.g. ./build.sh --packages-select htn_control
set -e
cd "$(dirname "$0")/ros2_ws"
colcon build --symlink-install "$@"
