from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    camera = LaunchConfiguration('camera')
    head_camera = LaunchConfiguration('head_camera')

    return LaunchDescription([
        DeclareLaunchArgument('camera', default_value='realsense',
                              description='Camera backend: realsense | none'),
        # Defaults fit a USB 2 link; on USB 3 go up to e.g. 640x480x30
        DeclareLaunchArgument('color_profile', default_value='640x480x15'),
        DeclareLaunchArgument('depth_profile', default_value='480x270x15'),
        # Declared by the launch files that include this one; here for a run on its own ('' = the package's)
        DeclareLaunchArgument('params_file', default_value=''),
        # none by default: a launch with no phone must not print errors without end
        DeclareLaunchArgument('head_camera', default_value='none',
                              description='Head camera backend: iphone | none'),

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
                # The IMU of a D435i as one /camera/imu (2 = the accelerometer interpolated onto
                # the gyro's samples). A camera with no IMU only logs that it has none.
                'enable_gyro': True,
                'enable_accel': True,
                'unite_imu_method': 2,
            }],
            condition=IfCondition(PythonExpression(["'", camera, "' == 'realsense'"])),
            output='screen',
        ),

        # Which way the hand points, from that IMU: /hand/orientation (hand_orientation_node.py).
        # It publishes nothing until IMU samples arrive, so it is harmless with a D435.
        Node(
            package='htn_control',
            executable='hand_orientation_node',
            name='hand_orientation',
            parameters=[{'params_file': LaunchConfiguration('params_file')}],
            condition=IfCondition(PythonExpression(["'", camera, "' == 'realsense'"])),
            output='screen',
        ),

        # Head camera HAL: /head_camera/color/image_raw/compressed + camera_info, whatever the
        # camera is. The forehead iPhone (Record3D app, USB); its rotation and size are node
        # parameters and part of a recorded dataset (docs/specs/iphone-camera-design.md).
        Node(
            package='htn_control',
            executable='iphone_camera_node',
            name='iphone_camera',
            condition=IfCondition(PythonExpression(["'", head_camera, "' == 'iphone'"])),
            output='screen',
        ),
    ])
