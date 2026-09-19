from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    description_pkg = FindPackageShare('htn_description')
    xacro_file = PathJoinSubstitution([description_pkg, 'urdf', 'hand.urdf.xacro'])

    params_file = LaunchConfiguration('params_file')
    foxglove = LaunchConfiguration('foxglove')

    robot_description = ParameterValue(
        Command(['xacro ', xacro_file, ' params_file:=', params_file]),
        value_type=str)

    return LaunchDescription([
        DeclareLaunchArgument(
            'params_file',
            default_value=PathJoinSubstitution([description_pkg, 'config', 'hand_params.yaml']),
            description='Physical parameters of the hand'),
        DeclareLaunchArgument('serial_port', default_value='/dev/ttyACM0'),
        DeclareLaunchArgument('baud_rate', default_value='1000000'),
        DeclareLaunchArgument('require_all_servos', default_value='true',
                              description='false = bench test with part of the servos'),
        DeclareLaunchArgument('passive', default_value='false',
                              description='Start with the torque off: fingers are moved by hand '
                                          '(demonstration recording). Toggle later with /hand/set_passive'),
        DeclareLaunchArgument('teleop', default_value='true',
                              description='Open the finger control window'),
        DeclareLaunchArgument('foxglove', default_value='true',
                              description='Start foxglove_bridge on ws://localhost:8765'),
        DeclareLaunchArgument('max_speed', default_value='2.0',
                              description='HAL rate limit: fastest a finger may travel, in full ranges '
                                          'per second (2.0 = open to closed in 0.5 s)'),
        DeclareLaunchArgument('rosbridge_port', default_value='9090',
                              description='Set ROSBRIDGE_PORT for application/ to match'),
        DeclareLaunchArgument('rosbridge', default_value='true',
                              description='Start rosbridge on ws://localhost:9090 (application/ backend)'),

        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            parameters=[{'robot_description': robot_description}],
        ),


        # The URDF is a tree, the finger linkages have loops: this closes them
        # by publishing the passive joints next to the driven ones
        Node(
            package='htn_control',
            executable='linkage_publisher',
            parameters=[{'params_file': params_file}],
        ),

        # HAL: /hand/command (0..1 per finger) -> servo bus. Also
        # publishes /joint_states so the model in Foxglove follows the hand.
        Node(
            package='htn_control',
            executable='hal',
            parameters=[{'backend': 'feetech', 'params_file': params_file,
                         'serial_port': LaunchConfiguration('serial_port'),
                         'baud_rate': ParameterValue(LaunchConfiguration('baud_rate'), value_type=int),
                         'require_all_servos': ParameterValue(
                             LaunchConfiguration('require_all_servos'), value_type=bool),
                         'max_speed': ParameterValue(LaunchConfiguration('max_speed'), value_type=float),
                         'passive': ParameterValue(LaunchConfiguration('passive'), value_type=bool)}],
            output='screen',
        ),

        Node(
            package='htn_control',
            executable='teleop_gui',
            condition=IfCondition(LaunchConfiguration('teleop')),
        ),

        # Camera HAL: /camera/color/..., /camera/depth/... (see camera.launch.py).
        # camera:=none turns it off; color_profile:= / depth_profile:= pass through.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution(
                [FindPackageShare('htn_launch'), 'launch', 'camera.launch.py']))),

        Node(
            package='foxglove_bridge',
            executable='foxglove_bridge',
            parameters=[{'port': 8765}],
            condition=IfCondition(foxglove),
        ),

        # Websocket JSON bridge for the web simulator in application/
        Node(
            package='rosbridge_server',
            executable='rosbridge_websocket',
            parameters=[{'port': ParameterValue(LaunchConfiguration('rosbridge_port'), value_type=int)}],
            condition=IfCondition(LaunchConfiguration('rosbridge')),
        ),
    ])
