#!/usr/bin/env python3

import sys
import time

import rclpy
from action_msgs.msg import GoalStatus
from pdr_robot_msgs.action import ExecuteBehavior
from pdr_robot_msgs.msg import BusinessStep, RobotState
from pdr_robot_msgs.srv import SetEmergencyStop
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data


class GazeboSilCheck(Node):
    def __init__(self):
        super().__init__("pdr_gazebo_sil_check")
        self.state = None
        self.business_steps = []
        self.create_subscription(
            RobotState, "robot/state", self._on_state, qos_profile_sensor_data)
        self.create_subscription(
            BusinessStep, "robot/business_steps", self._on_business_step, 100)
        self.stop_client = self.create_client(
            SetEmergencyStop, "robot/set_emergency_stop")
        self.behavior_client = ActionClient(
            self, ExecuteBehavior, "robot/execute_behavior")

    def _on_state(self, message):
        self.state = message

    def _on_business_step(self, message):
        self.business_steps.append(message)

    def _spin_until(self, predicate, deadline, error):
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if predicate():
                return
        raise RuntimeError(error)

    def run(self, timeout_seconds=45.0):
        deadline = time.monotonic() + timeout_seconds
        while (time.monotonic() < deadline
               and not self.stop_client.wait_for_service(0.1)):
            rclpy.spin_once(self, timeout_sec=0.1)
        if not self.stop_client.service_is_ready():
            raise RuntimeError("emergency-stop service did not become ready")

        self._spin_until(
            lambda: (self.state is not None
                     and self.state.lifecycle_state == "active"
                     and self.state.simulated
                     and self.state.simulator_backend == "gazebo"),
            deadline,
            "active Gazebo state was not observed")

        request = SetEmergencyStop.Request()
        request.engaged = False
        request.reason = "gazebo SIL check"
        future = self.stop_client.call_async(request)
        self._spin_until(
            future.done, deadline, "startup interlock request timed out")
        if not future.done() or not future.result().accepted:
            raise RuntimeError("startup interlock could not be released")

        self._spin_until(
            lambda: self.behavior_client.server_is_ready()
            or self.behavior_client.wait_for_server(timeout_sec=0.1),
            deadline,
            "behavior action server did not become ready")

        initial_x = self.state.pose.position.x
        goal = ExecuteBehavior.Goal()
        goal.behavior = "inspection/patrol"
        goal.parameters_json = '{"asset":"gazebo_demo_cell"}'
        goal_future = self.behavior_client.send_goal_async(goal)
        self._spin_until(goal_future.done, deadline, "business goal was not accepted")
        goal_handle = goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            raise RuntimeError("inspection/patrol business goal was rejected")

        result_future = goal_handle.get_result_async()
        self._spin_until(result_future.done, deadline, "business mission timed out")
        wrapped_result = result_future.result()
        if (wrapped_result.status != GoalStatus.STATUS_SUCCEEDED
                or not wrapped_result.result.success):
            raise RuntimeError(
                "business mission failed: " + wrapped_result.result.detail)

        expected_steps = {
            "sensor_self_check",
            "patrol_to_asset",
            "analyze_asset",
            "return_home",
        }
        self._spin_until(
            lambda: expected_steps.issubset(
                {
                    step.step for step in self.business_steps
                    if step.module == "inspection" and step.mission == "patrol"
                }),
            deadline,
            "business step trace was incomplete")
        records = {
            step.step: step for step in self.business_steps
            if step.module == "inspection" and step.mission == "patrol"
        }
        failed = [
            name for name in expected_steps
            if records[name].status != BusinessStep.SUCCEEDED
        ]
        if failed:
            raise RuntimeError("business steps failed: " + ",".join(failed))
        if abs(self.state.pose.position.x - initial_x) > 0.08:
            raise RuntimeError("inspection robot did not return to its start position")

        trace = ",".join(
            f"{name}:{records[name].duration_nanoseconds}ns"
            for name in sorted(expected_steps))
        print(f"PDR_GAZEBO_BUSINESS_TRACE {trace}", flush=True)
        print("PDR_GAZEBO_SIL_PASS", flush=True)


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
