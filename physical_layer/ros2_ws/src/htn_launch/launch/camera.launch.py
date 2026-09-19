from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    camera = LaunchConfiguration('camera')

    return LaunchDescription([
        DeclareLaunchArgument('camera', default_value='realsense',
                              description='Camera backend: realsense | none'),
        # Defaults fit a USB 2 link; on USB 3 go up to e.g. 640x480x30
        DeclareLaunchArgument('color_profile', default_value='640x480x15'),
        DeclareLaunchArgument('depth_profile', default_value='480x270x15'),

        # Camera HAL: whatever the camera is, it shows up as /camera/color/...,
        # /camera/depth/... and /camera/aligned_depth_to_color/... (node name
        # 'camera' in the root namespace gives exactly those topic names).
        # A new camera = a new Node here publishing the same topics.
        Node(
            package='realsense2_camera',
            executable='realsense2_camera_node',
            name='camera',
            namespace='/',  # the driver defaults to /camera/camera/... otherwise
            parameters=[{
                'camera_name': 'camera',
                # Started bare, the driver turns the infrared streams on, and
                # their resolution then fights depth_profile: no frames at all
                'enable_infra1': False,
                'enable_infra2': False,
                'rgb_camera.color_profile': LaunchConfiguration('color_profile'),
                'depth_module.depth_profile': LaunchConfiguration('depth_profile'),
                'align_depth.enable': True,
            }],
            condition=IfCondition(PythonExpression(["'", camera, "' == 'realsense'"])),
            output='screen',
        ),
    ])
