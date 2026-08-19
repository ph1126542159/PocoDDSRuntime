from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("config", description="Absolute simulator bridge YAML path"),
        Node(
            package="pdr_sim_bridge_ros2",
            executable="pdr_sim_bridge_node",
            name="pdr_sim_bridge",
            output="screen",
            parameters=[LaunchConfiguration("config")],
        ),
    ])
