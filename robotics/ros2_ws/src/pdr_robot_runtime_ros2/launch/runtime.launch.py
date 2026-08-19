from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, TimerAction
from launch.events import matches_action
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def generate_launch_description():
    runtime = LifecycleNode(
        package="pdr_robot_runtime_ros2",
        executable="pdr_robot_runtime_node",
        name="pdr_robot_runtime",
        output="screen",
        parameters=[LaunchConfiguration("config")],
    )
    configure = EmitEvent(event=ChangeState(
        lifecycle_node_matcher=matches_action(runtime),
        transition_id=Transition.TRANSITION_CONFIGURE,
    ))
    activate = EmitEvent(event=ChangeState(
        lifecycle_node_matcher=matches_action(runtime),
        transition_id=Transition.TRANSITION_ACTIVATE,
    ))
    return LaunchDescription([
        DeclareLaunchArgument("config", description="Absolute runtime YAML path"),
        runtime,
        TimerAction(period=0.5, actions=[configure]),
        TimerAction(period=2.0, actions=[activate]),
    ])
