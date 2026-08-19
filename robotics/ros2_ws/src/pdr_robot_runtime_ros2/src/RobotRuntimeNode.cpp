#include "PocoDDS/Robotics/RobotRuntime.h"

#include "geometry_msgs/msg/twist.hpp"
#include "lifecycle_msgs/msg/state.hpp"
#include "pdr_robot_msgs/action/execute_behavior.hpp"
#include "pdr_robot_msgs/msg/robot_command.hpp"
#include "pdr_robot_msgs/msg/robot_state.hpp"
#include "pdr_robot_msgs/msg/safety_state.hpp"
#include "pdr_robot_msgs/srv/set_emergency_stop.hpp"
#include "rclcpp/rclcpp.hpp"
#include "rclcpp_action/rclcpp_action.hpp"
#include "rclcpp_lifecycle/lifecycle_node.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

using namespace std::chrono_literals;

namespace pdr_robot_runtime_ros2
{
class RobotRuntimeNode final : public rclcpp_lifecycle::LifecycleNode
{
public:
    using Behavior = pdr_robot_msgs::action::ExecuteBehavior;
    using GoalHandle = rclcpp_action::ServerGoalHandle<Behavior>;
    using CallbackReturn = rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn;

    RobotRuntimeNode() : LifecycleNode("pdr_robot_runtime")
    {
        declare_parameter("world", "empty");
        declare_parameter("tick_period_ms", 20);
        declare_parameter("maximum_linear_speed", 1.0);
        declare_parameter("maximum_angular_speed", 1.0);
        declare_parameter("command_timeout_ms", 250);
        declare_parameter<std::vector<std::string>>("joint_names", {});
        declare_parameter<std::vector<double>>("joint_min_positions", {});
        declare_parameter<std::vector<double>>("joint_max_positions", {});
        declare_parameter<std::vector<double>>("joint_max_velocities", {});
        declare_parameter<std::vector<double>>("joint_max_efforts", {});
    }

    CallbackReturn on_configure(const rclcpp_lifecycle::State&) override
    {
        PocoDDS::Robotics::SafetyLimits limits;
        limits.maximumLinearSpeed = get_parameter("maximum_linear_speed").as_double();
        limits.maximumAngularSpeed = get_parameter("maximum_angular_speed").as_double();
        limits.commandTimeout = std::chrono::milliseconds(
            get_parameter("command_timeout_ms").as_int());
        if (limits.maximumLinearSpeed <= 0.0 || limits.maximumAngularSpeed <= 0.0 ||
            limits.commandTimeout.count() <= 0)
        {
            RCLCPP_ERROR(get_logger(), "Base safety limits and watchdog must be positive");
            return CallbackReturn::FAILURE;
        }
        const auto names = get_parameter("joint_names").as_string_array();
        const auto minimums = get_parameter("joint_min_positions").as_double_array();
        const auto maximums = get_parameter("joint_max_positions").as_double_array();
        const auto velocities = get_parameter("joint_max_velocities").as_double_array();
        const auto efforts = get_parameter("joint_max_efforts").as_double_array();
        if (minimums.size() != names.size() || maximums.size() != names.size() ||
            velocities.size() != names.size() || efforts.size() != names.size())
        {
            RCLCPP_ERROR(get_logger(), "All joint limit arrays must match joint_names");
            return CallbackReturn::FAILURE;
        }
        for (std::size_t index = 0; index < names.size(); ++index)
        {
            const auto inserted = limits.joints.emplace(
                names[index], PocoDDS::Robotics::JointSafetyLimit{
                    minimums[index], maximums[index], velocities[index], efforts[index]});
            if (names[index].empty() || !inserted.second || minimums[index] > maximums[index] ||
                velocities[index] <= 0.0 || efforts[index] <= 0.0)
            {
                RCLCPP_ERROR(get_logger(), "Invalid or duplicate joint safety limit at index %zu",
                             index);
                return CallbackReturn::FAILURE;
            }
        }
        _runtime = std::make_unique<PocoDDS::Robotics::RobotRuntime>(
            std::make_unique<PocoDDS::Robotics::InMemorySimulator>(), limits);
        _runtime->setWorld(get_parameter("world").as_string());
        if (!_runtime->configure())
            return CallbackReturn::FAILURE;

        _statePublisher = create_publisher<pdr_robot_msgs::msg::RobotState>(
            "robot/state", rclcpp::SensorDataQoS());
        _safetyPublisher = create_publisher<pdr_robot_msgs::msg::SafetyState>(
            "robot/safety_state", rclcpp::QoS(1).transient_local().reliable());
        _commandSubscription = create_subscription<geometry_msgs::msg::Twist>(
            "robot/cmd_vel", rclcpp::QoS(10),
            std::bind(&RobotRuntimeNode::onVelocity, this, std::placeholders::_1));
        _robotCommandSubscription = create_subscription<pdr_robot_msgs::msg::RobotCommand>(
            "robot/command", rclcpp::QoS(10),
            std::bind(&RobotRuntimeNode::onRobotCommand, this, std::placeholders::_1));
        _emergencyStopService = create_service<pdr_robot_msgs::srv::SetEmergencyStop>(
            "robot/set_emergency_stop",
            std::bind(&RobotRuntimeNode::onEmergencyStop, this,
                      std::placeholders::_1, std::placeholders::_2));
        _actionServer = rclcpp_action::create_server<Behavior>(
            this, "robot/execute_behavior",
            std::bind(&RobotRuntimeNode::onGoal, this,
                      std::placeholders::_1, std::placeholders::_2),
            std::bind(&RobotRuntimeNode::onCancel, this, std::placeholders::_1),
            std::bind(&RobotRuntimeNode::onAccepted, this, std::placeholders::_1));

        const auto tickMs = std::max<std::int64_t>(1, get_parameter("tick_period_ms").as_int());
        _timer = create_wall_timer(std::chrono::milliseconds(tickMs),
                                  std::bind(&RobotRuntimeNode::tick, this));
        return CallbackReturn::SUCCESS;
    }

    CallbackReturn on_activate(const rclcpp_lifecycle::State&) override
    {
        if (!_runtime || !_runtime->activate())
            return CallbackReturn::FAILURE;
        _statePublisher->on_activate();
        _safetyPublisher->on_activate();
        publishSafety(true, false, "startup interlock");
        return CallbackReturn::SUCCESS;
    }

    CallbackReturn on_deactivate(const rclcpp_lifecycle::State&) override
    {
        abortActiveGoal("lifecycle deactivated");
        if (_runtime)
        {
            _runtime->setEmergencyStop(true, "lifecycle inactive");
            _runtime->deactivate();
        }
        publishSafety(true, false, "lifecycle inactive");
        _statePublisher->on_deactivate();
        _safetyPublisher->on_deactivate();
        return CallbackReturn::SUCCESS;
    }

    CallbackReturn on_cleanup(const rclcpp_lifecycle::State&) override
    {
        if (_runtime)
            _runtime->cleanup();
        _runtime.reset();
        _timer.reset();
        _actionServer.reset();
        _emergencyStopService.reset();
        _commandSubscription.reset();
        _robotCommandSubscription.reset();
        _safetyPublisher.reset();
        _statePublisher.reset();
        return CallbackReturn::SUCCESS;
    }

    CallbackReturn on_shutdown(const rclcpp_lifecycle::State&) override
    {
        abortActiveGoal("runtime shutdown");
        if (_runtime)
            _runtime->shutdown();
        return CallbackReturn::SUCCESS;
    }

private:
    rclcpp_action::GoalResponse onGoal(
        const rclcpp_action::GoalUUID&,
        std::shared_ptr<const Behavior::Goal> goal)
    {
        if (get_current_state().id() != lifecycle_msgs::msg::State::PRIMARY_STATE_ACTIVE ||
            goal->behavior.empty())
            return rclcpp_action::GoalResponse::REJECT;
        std::lock_guard<std::mutex> lock(_goalMutex);
        return _activeGoal ? rclcpp_action::GoalResponse::REJECT
                           : rclcpp_action::GoalResponse::ACCEPT_AND_EXECUTE;
    }

    rclcpp_action::CancelResponse onCancel(const std::shared_ptr<GoalHandle>)
    {
        return rclcpp_action::CancelResponse::ACCEPT;
    }

    void onAccepted(const std::shared_ptr<GoalHandle> goal)
    {
        std::lock_guard<std::mutex> lock(_goalMutex);
        _activeGoal = goal;
        _goalProgress = 0.0F;
    }

    void onVelocity(const geometry_msgs::msg::Twist::SharedPtr message)
    {
        if (!_runtime)
            return;
        PocoDDS::Robotics::Twist command;
        command.linear = {message->linear.x, message->linear.y, message->linear.z};
        command.angular = {message->angular.x, message->angular.y, message->angular.z};
        const auto decision = _runtime->commandVelocity(command);
        publishSafety(_runtime->emergencyStop(), decision.permitted, decision.reason);
    }

    void onRobotCommand(const pdr_robot_msgs::msg::RobotCommand::SharedPtr message)
    {
        if (!_runtime)
            return;
        PocoDDS::Robotics::RobotCommand command;
        command.sequence = message->sequence;
        command.baseVelocity.linear = {message->base_velocity.linear.x,
                                       message->base_velocity.linear.y,
                                       message->base_velocity.linear.z};
        command.baseVelocity.angular = {message->base_velocity.angular.x,
                                        message->base_velocity.angular.y,
                                        message->base_velocity.angular.z};
        for (const auto& joint : message->joints)
        {
            if (joint.mode > pdr_robot_msgs::msg::JointCommand::EFFORT)
            {
                publishSafety(_runtime->emergencyStop(), false,
                              "invalid joint command mode: " + joint.name);
                return;
            }
            command.joints.push_back(
                {joint.name,
                 static_cast<PocoDDS::Robotics::JointCommandMode>(joint.mode),
                 joint.value});
        }
        const auto decision = _runtime->command(command);
        publishSafety(_runtime->emergencyStop(), decision.permitted, decision.reason);
    }

    void onEmergencyStop(
        const pdr_robot_msgs::srv::SetEmergencyStop::Request::SharedPtr request,
        pdr_robot_msgs::srv::SetEmergencyStop::Response::SharedPtr response)
    {
        if (!_runtime)
        {
            response->accepted = false;
            response->state = "not configured";
            return;
        }
        _runtime->setEmergencyStop(request->engaged, request->reason);
        response->accepted = true;
        response->state = request->engaged ? "engaged" : "released";
        publishSafety(request->engaged, false, response->state);
    }

    void tick()
    {
        if (!_runtime || _runtime->state() != PocoDDS::Robotics::LifecycleState::active)
            return;
        const auto tickMs = std::max<std::int64_t>(1, get_parameter("tick_period_ms").as_int());
        publishState(_runtime->step(std::chrono::milliseconds(tickMs)).state);
        tickAction();
    }

    void tickAction()
    {
        std::lock_guard<std::mutex> lock(_goalMutex);
        if (!_activeGoal)
            return;
        if (_activeGoal->is_canceling())
        {
            auto result = std::make_shared<Behavior::Result>();
            result->success = false;
            result->detail = "canceled";
            _activeGoal->canceled(result);
            _activeGoal.reset();
            return;
        }
        _goalProgress = std::min(1.0F, _goalProgress + 0.05F);
        auto feedback = std::make_shared<Behavior::Feedback>();
        feedback->progress = _goalProgress;
        feedback->current_step = _activeGoal->get_goal()->behavior;
        _activeGoal->publish_feedback(feedback);
        if (_goalProgress >= 1.0F)
        {
            auto result = std::make_shared<Behavior::Result>();
            result->success = true;
            result->detail = "completed by deterministic simulation executor";
            _activeGoal->succeed(result);
            _activeGoal.reset();
        }
    }

    void abortActiveGoal(const std::string& detail)
    {
        std::lock_guard<std::mutex> lock(_goalMutex);
        if (!_activeGoal)
            return;
        auto result = std::make_shared<Behavior::Result>();
        result->success = false;
        result->detail = detail;
        _activeGoal->abort(result);
        _activeGoal.reset();
    }

    void publishState(const PocoDDS::Robotics::RobotState& state)
    {
        if (!_statePublisher || !_statePublisher->is_activated())
            return;
        pdr_robot_msgs::msg::RobotState message;
        message.header.stamp = now();
        message.header.frame_id = state.frameId;
        message.lifecycle_state = "active";
        message.pose.position.x = state.pose.position.x;
        message.pose.position.y = state.pose.position.y;
        message.pose.position.z = state.pose.position.z;
        message.pose.orientation.x = state.pose.orientation.x;
        message.pose.orientation.y = state.pose.orientation.y;
        message.pose.orientation.z = state.pose.orientation.z;
        message.pose.orientation.w = state.pose.orientation.w;
        message.twist.linear.x = state.twist.linear.x;
        message.twist.linear.y = state.twist.linear.y;
        message.twist.linear.z = state.twist.linear.z;
        message.twist.angular.x = state.twist.angular.x;
        message.twist.angular.y = state.twist.angular.y;
        message.twist.angular.z = state.twist.angular.z;
        message.simulated = true;
        message.simulator_backend = "in-memory";
        _statePublisher->publish(message);
    }

    void publishSafety(bool emergencyStop, bool permitted, const std::string& reason)
    {
        if (!_safetyPublisher || !_safetyPublisher->is_activated())
            return;
        pdr_robot_msgs::msg::SafetyState message;
        message.header.stamp = now();
        message.emergency_stop = emergencyStop;
        message.command_permitted = permitted;
        message.reason = reason;
        _safetyPublisher->publish(message);
    }

    std::unique_ptr<PocoDDS::Robotics::RobotRuntime> _runtime;
    rclcpp_lifecycle::LifecyclePublisher<pdr_robot_msgs::msg::RobotState>::SharedPtr
        _statePublisher;
    rclcpp_lifecycle::LifecyclePublisher<pdr_robot_msgs::msg::SafetyState>::SharedPtr
        _safetyPublisher;
    rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr _commandSubscription;
    rclcpp::Subscription<pdr_robot_msgs::msg::RobotCommand>::SharedPtr
        _robotCommandSubscription;
    rclcpp::Service<pdr_robot_msgs::srv::SetEmergencyStop>::SharedPtr _emergencyStopService;
    rclcpp_action::Server<Behavior>::SharedPtr _actionServer;
    rclcpp::TimerBase::SharedPtr _timer;
    std::mutex _goalMutex;
    std::shared_ptr<GoalHandle> _activeGoal;
    float _goalProgress{0.0F};
};
} // namespace pdr_robot_runtime_ros2

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);
    auto node = std::make_shared<pdr_robot_runtime_ros2::RobotRuntimeNode>();
    rclcpp::executors::MultiThreadedExecutor executor;
    executor.add_node(node->get_node_base_interface());
    executor.spin();
    rclcpp::shutdown();
    return 0;
}
