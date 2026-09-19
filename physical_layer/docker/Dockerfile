# Dev image for machines that cannot run ROS 2 Humble natively (Windows, mac,
# Ubuntu 24.04): Humble + Gazebo Fortress + everything sim.launch.py and
# application/dev.sh need. The repo is bind-mounted at /ws/htn-2026, so edits
# on the host are live; build/, install/, node_modules and .venv live in named
# volumes (a Windows bind mount is too slow for them). See run.sh next to this file.
FROM ros:humble-ros-base-jammy
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-humble-ros-gz \
      ros-humble-gz-ros2-control \
      ros-humble-ros2-control \
      ros-humble-ros2-controllers \
      ros-humble-xacro \
      ros-humble-robot-state-publisher \
      ros-humble-foxglove-bridge \
      ros-humble-rosbridge-server \
      python3-colcon-common-extensions \
      python3-tk python3-serial python3-yaml python3-venv python3-pytest \
      iproute2 curl ca-certificates git \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*
# Every shell has ROS and (once built) the workspace sourced
RUN echo 'source /opt/ros/humble/setup.bash' >> /root/.bashrc \
    && echo '[ -f /ws/htn-2026/physical_layer/ros2_ws/install/setup.bash ] && source /ws/htn-2026/physical_layer/ros2_ws/install/setup.bash' >> /root/.bashrc
WORKDIR /ws/htn-2026
CMD ["bash"]
