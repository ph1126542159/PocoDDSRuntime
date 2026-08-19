from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import EmitEvent, IncludeLaunchDescription, TimerAction
from launch.events import matches_action
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import LifecycleNode, Node
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def generate_launch_description():
    bringup = Path(get_package_share_directory("pdr_robot_bringup"))
    gz_share = Path(get_package_share_directory("ros_gz_sim"))
    world = bringup / "worlds" / "pdr_diff_drive.sdf"

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(gz_share / "launch" / "gz_sim.launch.py")),
        launch_arguments={"gz_args": f"-r -s {world}"}.items(),
    )
    transport_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name="pdr_gazebo_transport_bridge",
        output="screen",
        arguments=[
            "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
            "/model/pdr_bot/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist",
            "/model/pdr_bot/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry",
            "/world/pdr_world/model/pdr_bot/joint_state@sensor_msgs/msg/JointState[gz.msgs.Model",
        ],
    )
    simulation_bridge = Node(
        package="pdr_sim_bridge_ros2",
        executable="pdr_sim_bridge_node",
        name="pdr_sim_bridge",
        output="screen",
        parameters=[str(bringup / "config" / "gazebo_bridge.yaml")],
    )
    runtime = LifecycleNode(
        package="pdr_robot_runtime_ros2",
        executable="pdr_robot_runtime_node",
        name="pdr_robot_runtime",
        namespace="",
        output="screen",
        parameters=[str(bringup / "config" / "gazebo_runtime.yaml")],
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
        gazebo,
        transport_bridge,
        simulation_bridge,
        runtime,
        TimerAction(period=2.0, actions=[configure]),
        TimerAction(period=6.0, actions=[activate]),
    ])
