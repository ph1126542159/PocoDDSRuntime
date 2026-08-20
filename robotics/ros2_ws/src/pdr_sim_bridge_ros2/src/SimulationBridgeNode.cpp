#include "geometry_msgs/msg/twist.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "pdr_robot_msgs/msg/joint_command.hpp"
#include "pdr_robot_msgs/msg/robot_command.hpp"
#include "pdr_robot_msgs/msg/robot_frame.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/joint_state.hpp"
#include "std_msgs/msg/float64_multi_array.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

using namespace std::chrono_literals;

namespace pdr_sim_bridge_ros2
{
class SimulationBridgeNode final : public rclcpp::Node
{
  public:
    SimulationBridgeNode() : Node("pdr_sim_bridge")
    {
        declare_parameter("simulator_name", "gazebo");
        declare_parameter("frame_id", "world");
        declare_parameter("publish_period_ms", 20);
        declare_parameter("command_topic", "robot/sim/command");
        declare_parameter("frame_topic", "robot/sim/frame");
        declare_parameter("cmd_vel_topic", "cmd_vel");
        declare_parameter("odometry_topic", "odom");
        declare_parameter("joint_state_topic", "joint_states");
        declare_parameter("joint_command_topic", "joint_controller/commands");
        declare_parameter("joint_command_mode", "position");
        declare_parameter("joint_names", std::vector<std::string>{});

        _simulatorName = get_parameter("simulator_name").as_string();
        _frameId = get_parameter("frame_id").as_string();
        _jointNames = get_parameter("joint_names").as_string_array();
        const auto mode = get_parameter("joint_command_mode").as_string();
        if (mode == "position")
            _jointMode = pdr_robot_msgs::msg::JointCommand::POSITION;
        else if (mode == "velocity")
            _jointMode = pdr_robot_msgs::msg::JointCommand::VELOCITY;
        else if (mode == "effort")
            _jointMode = pdr_robot_msgs::msg::JointCommand::EFFORT;
        else
            throw std::invalid_argument("joint_command_mode must be position, velocity or effort");

        _velocityPublisher = create_publisher<geometry_msgs::msg::Twist>(
            get_parameter("cmd_vel_topic").as_string(), rclcpp::QoS(10).reliable());
        _jointCommandPublisher = create_publisher<std_msgs::msg::Float64MultiArray>(
            get_parameter("joint_command_topic").as_string(), rclcpp::QoS(10).reliable());
        _framePublisher = create_publisher<pdr_robot_msgs::msg::RobotFrame>(
            get_parameter("frame_topic").as_string(), rclcpp::SensorDataQoS());
        _commandSubscription = create_subscription<pdr_robot_msgs::msg::RobotCommand>(
            get_parameter("command_topic").as_string(), rclcpp::QoS(10).reliable(),
            std::bind(&SimulationBridgeNode::onCommand, this, std::placeholders::_1));
        _odometrySubscription = create_subscription<nav_msgs::msg::Odometry>(
            get_parameter("odometry_topic").as_string(), rclcpp::SensorDataQoS(),
            std::bind(&SimulationBridgeNode::onOdometry, this, std::placeholders::_1));
        _jointStateSubscription = create_subscription<sensor_msgs::msg::JointState>(
            get_parameter("joint_state_topic").as_string(), rclcpp::SensorDataQoS(),
            std::bind(&SimulationBridgeNode::onJointState, this, std::placeholders::_1));

        const auto period = std::max<std::int64_t>(1, get_parameter("publish_period_ms").as_int());
        _timer = create_wall_timer(std::chrono::milliseconds(period),
                                   std::bind(&SimulationBridgeNode::publishFrame, this));
    }

  private:
    void onCommand(const pdr_robot_msgs::msg::RobotCommand::SharedPtr message)
    {
        geometry_msgs::msg::Twist velocity = message->base_velocity;
        _velocityPublisher->publish(velocity);
        if (message->joints.empty())
            return;

        if (_jointNames.empty() || message->joints.size() != _jointNames.size())
        {
            RCLCPP_ERROR(get_logger(),
                         "Joint command must cover every configured joint exactly once");
            return;
        }
        std::unordered_map<std::string, double> requested;
        for (const auto& joint : message->joints)
        {
            if (joint.mode != _jointMode || !requested.emplace(joint.name, joint.value).second)
            {
                RCLCPP_ERROR(get_logger(), "Joint mode mismatch or duplicate joint: %s",
                             joint.name.c_str());
                return;
            }
        }
        std_msgs::msg::Float64MultiArray output;
        output.data.reserve(_jointNames.size());
        for (const auto& name : _jointNames)
        {
            const auto found = requested.find(name);
            if (found == requested.end())
            {
                RCLCPP_ERROR(get_logger(), "Missing configured joint: %s", name.c_str());
                return;
            }
            output.data.push_back(found->second);
        }
        _jointCommandPublisher->publish(output);
    }

    void onOdometry(const nav_msgs::msg::Odometry::SharedPtr message)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _odometry = *message;
        _haveOdometry = true;
    }

    void onJointState(const sensor_msgs::msg::JointState::SharedPtr message)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _jointState = *message;
        _haveJointState = true;
    }

    void publishFrame()
    {
        nav_msgs::msg::Odometry odometry;
        sensor_msgs::msg::JointState joints;
        bool haveOdometry = false;
        bool haveJoints = false;
        {
            std::lock_guard<std::mutex> lock(_mutex);
            odometry = _odometry;
            joints = _jointState;
            haveOdometry = _haveOdometry;
            haveJoints = _haveJointState;
        }
        if (!haveOdometry && !haveJoints)
            return;

        pdr_robot_msgs::msg::RobotFrame frame;
        frame.state.header.stamp = now();
        frame.state.header.frame_id =
            haveOdometry && !odometry.header.frame_id.empty() ? odometry.header.frame_id : _frameId;
        frame.state.lifecycle_state = "simulated";
        frame.state.simulated = true;
        frame.state.simulator_backend = _simulatorName;
        if (haveOdometry)
        {
            frame.state.pose = odometry.pose.pose;
            frame.state.twist = odometry.twist.twist;
        }
        if (haveJoints)
        {
            frame.state.joints = std::move(joints);
            frame.state.joints.header.stamp = frame.state.header.stamp;
        }
        _framePublisher->publish(frame);
    }

    std::string _simulatorName;
    std::string _frameId;
    std::vector<std::string> _jointNames;
    std::uint8_t _jointMode{pdr_robot_msgs::msg::JointCommand::POSITION};
    std::mutex _mutex;
    nav_msgs::msg::Odometry _odometry;
    sensor_msgs::msg::JointState _jointState;
    bool _haveOdometry{false};
    bool _haveJointState{false};
    rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr _velocityPublisher;
    rclcpp::Publisher<std_msgs::msg::Float64MultiArray>::SharedPtr _jointCommandPublisher;
    rclcpp::Publisher<pdr_robot_msgs::msg::RobotFrame>::SharedPtr _framePublisher;
    rclcpp::Subscription<pdr_robot_msgs::msg::RobotCommand>::SharedPtr _commandSubscription;
    rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr _odometrySubscription;
    rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr _jointStateSubscription;
    rclcpp::TimerBase::SharedPtr _timer;
};
} // namespace pdr_sim_bridge_ros2

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<pdr_sim_bridge_ros2::SimulationBridgeNode>());
    rclcpp::shutdown();
    return 0;
}
