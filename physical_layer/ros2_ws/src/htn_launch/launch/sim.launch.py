import os
import signal
from pathlib import Path

from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription, LogInfo,
                            OpaqueFunction, RegisterEventHandler, Shutdown)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit, OnShutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (Command, LaunchConfiguration,
                                  PathJoinSubstitution, PythonExpression)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def gazebo_servers():
    """pids of the Gazebo processes in our IGN_PARTITION."""
    partition = os.environ.get('IGN_PARTITION', '')
    found = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            command = (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            if 'ign gazebo' not in command:
                continue
            environ = (proc / 'environ').read_bytes().split(b'\0')
        except OSError:
            continue  # gone meanwhile, or somebody else's process
        theirs = next((e[14:].decode() for e in environ if e.startswith(b'IGN_PARTITION=')), '')
        if theirs == partition:
            found.append(int(proc.name))
    return sorted(found)


def stop_own_gazebo(context):
    """Ctrl-C reaches the shell that started `ign gazebo`, not always the server behind it, and
    a server that survives poisons the next launch (see refuse_stale_gazebo). Nothing else was
    in our partition when we started, so whatever is there now is ours."""
    for pid in gazebo_servers():
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return []


def refuse_stale_gazebo(context):
    """A Gazebo server left over from an earlier launch (Ctrl-C does not always take it down)
    shares our partition: the hand then gets spawned twice over, the controller spawner hangs,
    no /clock arrives and the HAL - which runs on sim time - freezes. Everything LOOKS alive:
    commands go out, nothing ever moves. Refuse to start in that state."""
    stale = gazebo_servers()
    if not stale:
        return []
    pids = ' '.join(str(pid) for pid in stale)
    return [LogInfo(msg=f'\n\n  A Gazebo server is already running in this partition (pid {pids}).\n'
                        f'  With it the sim starts half-dead: commands go out, the hand never moves.\n'
                        f'  Stop the other sim, or if it is a leftover:   kill -9 {pids}\n'),
            Shutdown(reason='stale Gazebo server')]


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

        OpaqueFunction(function=refuse_stale_gazebo),
        RegisterEventHandler(OnShutdown(on_shutdown=[OpaqueFunction(function=stop_own_gazebo)])),
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
