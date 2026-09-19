from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription,
                            RegisterEventHandler, Shutdown)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (Command, LaunchConfiguration,
                                  PathJoinSubstitution, PythonExpression)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    description_pkg = FindPackageShare('htn_description')
    launch_pkg = FindPackageShare('htn_launch')

    xacro_file = PathJoinSubstitution([description_pkg, 'urdf', 'hand.urdf.xacro'])
    controllers_file = PathJoinSubstitution([launch_pkg, 'config', 'controllers.yaml'])
    world = PathJoinSubstitution([launch_pkg, 'worlds', 'empty.sdf'])

    params_file = LaunchConfiguration('params_file')
    gui = LaunchConfiguration('gui')
    foxglove = LaunchConfiguration('foxglove')

    robot_description = ParameterValue(
        Command(['xacro ', xacro_file,
                 ' sim:=gazebo',
                 ' params_file:=', params_file,
                 ' controllers_file:=', controllers_file]),
        value_type=str)
    # Gazebo cannot close the loops of the finger linkages, and free passive
    # links would dangle: it simulates base + servo horns only. Everything that
    # draws the hand gets the full description above plus linkage_publisher.
    physics_description = Command(['xacro ', xacro_file,
                                   ' sim:=gazebo parts:=horns',
                                   ' params_file:=', params_file,
                                   ' controllers_file:=', controllers_file])

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution(
            [FindPackageShare('ros_gz_sim'), 'launch', 'gz_sim.launch.py'])),
        launch_arguments={
            # -s: server only (no Gazebo window)
            'gz_args': PythonExpression([
                "'-r ' + ('' if '", gui, "' == 'true' else '-s ') + '", world, "'"]),
        }.items(),
    )

    spawn = Node(
        package='ros_gz_sim',
        executable='create',
        arguments=['-string', physics_description, '-name', 'htn_hand'],
        output='screen',
    )

    joint_state_broadcaster = Node(
        package='controller_manager',
        executable='spawner',
        arguments=['joint_state_broadcaster'],
    )
    hand_position_controller = Node(
        package='controller_manager',
        executable='spawner',
        arguments=['hand_position_controller'],
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'params_file',
            default_value=PathJoinSubstitution([description_pkg, 'config', 'hand_params.yaml']),
            description='Physical parameters of the hand'),
        DeclareLaunchArgument('gui', default_value='false',
                              description='Open the Gazebo window (Foxglove is the default viewer)'),
        DeclareLaunchArgument('teleop', default_value='true',
                              description='Open the finger control window'),
        DeclareLaunchArgument('foxglove', default_value='true',
                              description='Start foxglove_bridge on ws://localhost:8765'),
        DeclareLaunchArgument('rosbridge', default_value='true',
                              description='Start rosbridge on ws://localhost:9090 (application/ backend)'),

        gazebo,
        # Without Gazebo the sim clock stops and the HAL (which runs on sim time)
        # silently freezes: the control window then looks alive but nothing
        # moves. Bring everything down instead so the failure is obvious.
        RegisterEventHandler(OnProcessExit(
            on_exit=lambda event, context: (
                [Shutdown(reason='Gazebo exited - shutting the sim down')]
                if 'gazebo' in event.process_name else None))),
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            parameters=[{'robot_description': robot_description,
                         'use_sim_time': True}],
        ),
        spawn,
        Node(
            package='ros_gz_bridge',
            executable='parameter_bridge',
            arguments=['/clock@rosgraph_msgs/msg/Clock[ignition.msgs.Clock'],
        ),
        # The controller_manager lives inside Gazebo and only exists once the
        # hand has been spawned
        RegisterEventHandler(OnProcessExit(
            target_action=spawn, on_exit=[joint_state_broadcaster])),
        RegisterEventHandler(OnProcessExit(
            target_action=joint_state_broadcaster, on_exit=[hand_position_controller])),


        # The URDF is a tree, the finger linkages have loops: this closes them
        # by publishing the passive joints next to the driven ones
        Node(
            package='htn_control',
            executable='linkage_publisher',
            parameters=[{'params_file': params_file, 'use_sim_time': True}],
        ),

        # HAL: /hand/command (0..1 per finger) -> simulated servos
        Node(
            package='htn_control',
            executable='hal',
            parameters=[{'backend': 'sim', 'params_file': params_file,
                         'use_sim_time': True}],
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
            parameters=[{'port': 8765, 'use_sim_time': True}],
            condition=IfCondition(foxglove),
        ),

        # Websocket JSON bridge for the web simulator in application/
        Node(
            package='rosbridge_server',
            executable='rosbridge_websocket',
            parameters=[{'port': 9090}],
            condition=IfCondition(LaunchConfiguration('rosbridge')),
        ),
    ])
