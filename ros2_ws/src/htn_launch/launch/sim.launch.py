from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import LaunchConfigurationEquals
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('mode', default_value='teleop',
                              choices=['teleop', 'vla'],
                              description='Who drives the fingers'),

        # TODO: simulator, robot description, controllers

        Node(
            package='htn_control',
            executable='teleop',
            output='screen',
            condition=LaunchConfigurationEquals('mode', 'teleop'),
        ),
        Node(
            package='htn_vla',
            executable='vla',
            output='screen',
            condition=LaunchConfigurationEquals('mode', 'vla'),
        ),
    ])
