#include "PocoDDS/Robotics/MockHardware.h"
#include "PocoDDS/Robotics/RobotRuntime.h"

#include "pdr_robot_msgs/action/execute_behavior.hpp"
#include "pdr_robot_msgs/msg/joint_command.hpp"
#include "pdr_robot_msgs/msg/robot_command.hpp"
#include "pdr_robot_msgs/msg/robot_frame.hpp"
#include "pdr_robot_msgs/srv/set_emergency_stop.hpp"
#include "gtest/gtest.h"

#include <chrono>
#include <memory>
#include <vector>

TEST(RobotContract, generatedInterfacesAndCoreAgree)
{
    pdr_robot_msgs::msg::RobotCommand message;
    message.sequence = 7;
    pdr_robot_msgs::msg::JointCommand joint;
    joint.name = "joint1";
    joint.mode = pdr_robot_msgs::msg::JointCommand::POSITION;
    joint.value = 0.5;
    message.joints.push_back(joint);

    PocoDDS::Robotics::SafetyLimits limits;
    limits.joints.emplace("joint1", PocoDDS::Robotics::JointSafetyLimit{-1.0, 1.0, 2.0, 3.0});
    auto hardware =
        std::make_unique<PocoDDS::Robotics::MockHardware>(std::vector<std::string>{"joint1"});
    PocoDDS::Robotics::RobotRuntime runtime(std::move(hardware), limits);
    runtime.setBackendDescription("mock://contract-test");
    ASSERT_TRUE(runtime.configure());
    ASSERT_TRUE(runtime.activate());
    runtime.setEmergencyStop(false);

    PocoDDS::Robotics::RobotCommand command;
    command.sequence = message.sequence;
    command.joints.push_back(
        {joint.name, PocoDDS::Robotics::JointCommandMode::position, joint.value});
    EXPECT_TRUE(runtime.command(command).permitted);
    EXPECT_DOUBLE_EQ(runtime.step(std::chrono::milliseconds(10)).state.joints.front().position,
                     0.5);

    pdr_robot_msgs::msg::RobotFrame frame;
    pdr_robot_msgs::srv::SetEmergencyStop::Request request;
    pdr_robot_msgs::action::ExecuteBehavior::Goal goal;
    EXPECT_TRUE(frame.state.joints.name.empty());
    EXPECT_FALSE(request.engaged);
    EXPECT_TRUE(goal.behavior.empty());
}
