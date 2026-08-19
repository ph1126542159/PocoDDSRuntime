#!/usr/bin/env python3

import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from pdr_robot_msgs.msg import RobotState
from pdr_robot_msgs.srv import SetEmergencyStop
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data


class GazeboSilCheck(Node):
    def __init__(self):
        super().__init__("pdr_gazebo_sil_check")
        self.state = None
        self.initial_x = None
        self.create_subscription(
            RobotState, "robot/state", self._on_state, qos_profile_sensor_data)
        self.command = self.create_publisher(Twist, "robot/cmd_vel", 10)
        self.stop_client = self.create_client(
            SetEmergencyStop, "robot/set_emergency_stop")

    def _on_state(self, message):
        self.state = message

    def run(self, timeout_seconds=45.0):
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and not self.stop_client.wait_for_service(0.1):
            rclpy.spin_once(self, timeout_sec=0.1)
        if not self.stop_client.service_is_ready():
            raise RuntimeError("emergency-stop service did not become ready")

        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if (self.state is not None and self.state.lifecycle_state == "active"
                    and self.state.simulated
                    and self.state.simulator_backend == "gazebo"):
                break
        else:
            raise RuntimeError("active Gazebo state was not observed")

        request = SetEmergencyStop.Request()
        request.engaged = False
        request.reason = "gazebo SIL check"
        future = self.stop_client.call_async(request)
        while time.monotonic() < deadline and not future.done():
            rclpy.spin_once(self, timeout_sec=0.1)
        if not future.done() or not future.result().accepted:
            raise RuntimeError("startup interlock could not be released")

        self.initial_x = self.state.pose.position.x
        velocity = Twist()
        velocity.linear.x = 0.35
        while time.monotonic() < deadline:
            self.command.publish(velocity)
            rclpy.spin_once(self, timeout_sec=0.05)
            if self.state is not None and self.state.pose.position.x - self.initial_x >= 0.05:
                self.command.publish(Twist())
                print("PDR_GAZEBO_SIL_PASS", flush=True)
                return
        self.command.publish(Twist())
        raise RuntimeError("robot did not move far enough in Gazebo")


def main():
    rclpy.init()
    node = GazeboSilCheck()
    try:
        node.run()
    except Exception as exception:
        node.get_logger().error(str(exception))
        return_code = 1
    else:
        return_code = 0
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return return_code


if __name__ == "__main__":
    sys.exit(main())
