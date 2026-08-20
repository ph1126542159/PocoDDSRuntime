#include "PocoDDS/Robotics/Behavior.h"
#include "PocoDDS/Robotics/Business.h"
#include "PocoDDS/Robotics/BusinessPlugin.h"
#include "PocoDDS/Robotics/ExternalHardware.h"
#include "PocoDDS/Robotics/MockHardware.h"
#include "PocoDDS/Robotics/ReferenceBusinessModules.h"
#include "PocoDDS/Robotics/RobotRuntime.h"
#include "PocoDDS/Robotics/SimulationAdapter.h"

#include "geometry_msgs/msg/twist.hpp"
#include "lifecycle_msgs/msg/state.hpp"
#include "pdr_robot_msgs/action/execute_behavior.hpp"
#include "pdr_robot_msgs/msg/business_step.hpp"
#include "pdr_robot_msgs/msg/robot_command.hpp"
#include "pdr_robot_msgs/msg/robot_frame.hpp"
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
#include <iomanip>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
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
    using CallbackReturn =
        rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn;

    RobotRuntimeNode() : LifecycleNode("pdr_robot_runtime")
    {
        declare_parameter("backend", "in_memory");
        declare_parameter("world", "empty");
        declare_parameter("hardware_description", "mock://robot");
        declare_parameter("simulator_name", "external-simulator");
        declare_parameter("hardware_name", "external-hardware");
        declare_parameter("simulator_feedback_timeout_ms", 500);
        declare_parameter("tick_period_ms", 20);
        declare_parameter("maximum_linear_speed", 1.0);
        declare_parameter("maximum_angular_speed", 1.0);
        declare_parameter("command_timeout_ms", 250);
        declare_parameter<std::vector<std::string>>("joint_names", {});
        declare_parameter<std::vector<double>>("joint_min_positions", {});
        declare_parameter<std::vector<double>>("joint_max_positions", {});
        declare_parameter<std::vector<double>>("joint_max_velocities", {});
        declare_parameter<std::vector<double>>("joint_max_efforts", {});
        declare_parameter<std::vector<std::string>>("business_modules", {});
        declare_parameter<std::vector<std::string>>("business_plugins", {});
        if (!PocoDDS::Robotics::registerReferenceBusinessModules(_businessModules))
            throw std::logic_error("reference business module registration failed");
        _orchestrator.registerBehavior(
            "self_test",
            []
            {
                auto ticks = std::make_shared<std::size_t>(0);
                return std::make_unique<PocoDDS::Robotics::BehaviorTask>(
                    [ticks](PocoDDS::Robotics::BehaviorBlackboard& blackboard)
                    {
                        ++*ticks;
                        blackboard["current_step"] = "self_test_" + std::to_string(*ticks);
                        return *ticks >= 3 ? PocoDDS::Robotics::BehaviorStatus::succeeded
                                           : PocoDDS::Robotics::BehaviorStatus::running;
                    });
            });
        _orchestrator.registerBehavior(
            "hold",
            []
            {
                return std::make_unique<PocoDDS::Robotics::BehaviorTask>(
                    [](PocoDDS::Robotics::BehaviorBlackboard&)
                    { return PocoDDS::Robotics::BehaviorStatus::running; });
            });
    }

    CallbackReturn on_configure(const rclcpp_lifecycle::State&) override
    {
        clearBusinessRuntime();
        _runtimeFaulted = false;
        PocoDDS::Robotics::SafetyLimits limits;
        limits.maximumLinearSpeed = get_parameter("maximum_linear_speed").as_double();
        limits.maximumAngularSpeed = get_parameter("maximum_angular_speed").as_double();
        limits.commandTimeout =
            std::chrono::milliseconds(get_parameter("command_timeout_ms").as_int());
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
                names[index],
                PocoDDS::Robotics::JointSafetyLimit{minimums[index], maximums[index],
                                                    velocities[index], efforts[index]});
            if (names[index].empty() || !inserted.second || minimums[index] > maximums[index] ||
                velocities[index] <= 0.0 || efforts[index] <= 0.0)
            {
                RCLCPP_ERROR(get_logger(), "Invalid or duplicate joint safety limit at index %zu",
                             index);
                return CallbackReturn::FAILURE;
            }
        }
        const auto backend = get_parameter("backend").as_string();
        std::unique_ptr<PocoDDS::Robotics::RobotBackend> robotBackend;
        if (backend == "in_memory")
        {
            robotBackend = std::make_unique<PocoDDS::Robotics::InMemorySimulator>();
            _backendName = "in-memory";
            _simulated = true;
        }
        else if (backend == "mock_hardware")
        {
            robotBackend = std::make_unique<PocoDDS::Robotics::MockHardware>(names);
            _backendName = "mock-hardware";
            _simulated = false;
        }
        else if (backend == "topic_simulation")
        {
            const auto feedbackTimeout =
                std::chrono::milliseconds(get_parameter("simulator_feedback_timeout_ms").as_int());
            if (feedbackTimeout.count() <= 0)
            {
                RCLCPP_ERROR(get_logger(), "simulator_feedback_timeout_ms must be positive");
                return CallbackReturn::FAILURE;
            }
            _backendCommandPublisher = create_publisher<pdr_robot_msgs::msg::RobotCommand>(
                "robot/sim/command", rclcpp::QoS(10).reliable());
            auto external = std::make_unique<PocoDDS::Robotics::ExternalSimulator>(
                get_parameter("simulator_name").as_string(),
                [this](const PocoDDS::Robotics::RobotCommand& command)
                { return publishBackendCommand(command); }, feedbackTimeout);
            _externalSimulator = external.get();
            robotBackend = std::move(external);
            _backendName = get_parameter("simulator_name").as_string();
            _simulated = true;
        }
        else if (backend == "topic_hardware")
        {
            const auto feedbackTimeout =
                std::chrono::milliseconds(get_parameter("simulator_feedback_timeout_ms").as_int());
            if (feedbackTimeout.count() <= 0)
            {
                RCLCPP_ERROR(get_logger(), "simulator_feedback_timeout_ms must be positive");
                return CallbackReturn::FAILURE;
            }
            _backendCommandPublisher = create_publisher<pdr_robot_msgs::msg::RobotCommand>(
                "robot/hardware/command", rclcpp::QoS(10).reliable());
            auto external = std::make_unique<PocoDDS::Robotics::ExternalHardware>(
                get_parameter("hardware_name").as_string(),
                [this](const PocoDDS::Robotics::RobotCommand& command)
                { return publishBackendCommand(command); }, feedbackTimeout);
            _externalHardware = external.get();
            robotBackend = std::move(external);
            _backendName = get_parameter("hardware_name").as_string();
            _simulated = false;
        }
        else
        {
            RCLCPP_ERROR(get_logger(), "Unsupported backend: %s", backend.c_str());
            return CallbackReturn::FAILURE;
        }
        _runtime =
            std::make_unique<PocoDDS::Robotics::RobotRuntime>(std::move(robotBackend), limits);
        _runtime->setBackendDescription(backend == "mock_hardware" || backend == "topic_hardware"
                                            ? get_parameter("hardware_description").as_string()
                                            : get_parameter("world").as_string());
        if (!_runtime->configure())
            return CallbackReturn::FAILURE;

        _tickPeriod = std::chrono::milliseconds(
            std::max<std::int64_t>(1, get_parameter("tick_period_ms").as_int()));
        _businessContext =
            std::make_unique<PocoDDS::Robotics::BusinessContext>(*_runtime, _tickPeriod);
        _businessBehaviorNames.clear();
        for (const auto& plugin : get_parameter("business_plugins").as_string_array())
        {
            try
            {
                auto loaded = PocoDDS::Robotics::BusinessPluginLoader::load(plugin);
                if (!_businessModules.contains(loaded->name()) &&
                    !_businessModules.registerModule(std::move(loaded)))
                {
                    RCLCPP_ERROR(get_logger(), "Business plugin could not be registered: %s",
                                 plugin.c_str());
                    clearBusinessRuntime();
                    return CallbackReturn::FAILURE;
                }
            }
            catch (const std::exception& exception)
            {
                RCLCPP_ERROR(get_logger(), "Business plugin load failed: %s: %s", plugin.c_str(),
                             exception.what());
                clearBusinessRuntime();
                return CallbackReturn::FAILURE;
            }
        }
        for (const auto& module : get_parameter("business_modules").as_string_array())
        {
            if (!_businessModules.contains(module) ||
                !_businessModules.install(module, _orchestrator, *_businessContext))
            {
                RCLCPP_ERROR(get_logger(), "Business module could not be installed: %s",
                             module.c_str());
                clearBusinessRuntime();
                return CallbackReturn::FAILURE;
            }
            for (const auto& mission : _businessModules.missionNames(module))
            {
                _businessBehaviorNames.push_back(
                    PocoDDS::Robotics::BusinessModuleRegistry::qualifiedBehaviorName(module,
                                                                                     mission));
            }
        }

        if (_externalSimulator || _externalHardware)
        {
            const auto frameTopic = _externalHardware ? "robot/hardware/frame" : "robot/sim/frame";
            _backendFrameSubscription = create_subscription<pdr_robot_msgs::msg::RobotFrame>(
                frameTopic, rclcpp::SensorDataQoS(),
                std::bind(&RobotRuntimeNode::onBackendFrame, this, std::placeholders::_1));
        }

        _statePublisher = create_publisher<pdr_robot_msgs::msg::RobotState>(
            "robot/state", rclcpp::SensorDataQoS());
        _safetyPublisher = create_publisher<pdr_robot_msgs::msg::SafetyState>(
            "robot/safety_state", rclcpp::QoS(1).transient_local().reliable());
        _businessStepPublisher = create_publisher<pdr_robot_msgs::msg::BusinessStep>(
            "robot/business_steps", rclcpp::QoS(100).reliable());
        _commandSubscription = create_subscription<geometry_msgs::msg::Twist>(
            "robot/cmd_vel", rclcpp::QoS(10),
            std::bind(&RobotRuntimeNode::onVelocity, this, std::placeholders::_1));
        _robotCommandSubscription = create_subscription<pdr_robot_msgs::msg::RobotCommand>(
            "robot/command", rclcpp::QoS(10),
            std::bind(&RobotRuntimeNode::onRobotCommand, this, std::placeholders::_1));
        _emergencyStopService = create_service<pdr_robot_msgs::srv::SetEmergencyStop>(
            "robot/set_emergency_stop", std::bind(&RobotRuntimeNode::onEmergencyStop, this,
                                                  std::placeholders::_1, std::placeholders::_2));
        _actionServer = rclcpp_action::create_server<Behavior>(
            this, "robot/execute_behavior",
            std::bind(&RobotRuntimeNode::onGoal, this, std::placeholders::_1,
                      std::placeholders::_2),
            std::bind(&RobotRuntimeNode::onCancel, this, std::placeholders::_1),
            std::bind(&RobotRuntimeNode::onAccepted, this, std::placeholders::_1));

        _timer = create_wall_timer(_tickPeriod, std::bind(&RobotRuntimeNode::tick, this));
        return CallbackReturn::SUCCESS;
    }

    CallbackReturn on_activate(const rclcpp_lifecycle::State&) override
    {
        if (_runtime)
            _runtime->setEmergencyStop(true, "startup interlock");
        if (!_runtime || !_runtime->activate())
            return CallbackReturn::FAILURE;
        _runtimeFaulted = false;
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
        clearBusinessRuntime();
        _runtime.reset();
        _timer.reset();
        _actionServer.reset();
        _emergencyStopService.reset();
        _commandSubscription.reset();
        _robotCommandSubscription.reset();
        _backendFrameSubscription.reset();
        _backendCommandPublisher.reset();
        _externalSimulator = nullptr;
        _externalHardware = nullptr;
        _safetyPublisher.reset();
        _businessStepPublisher.reset();
        _statePublisher.reset();
        _runtimeFaulted = false;
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
    void clearBusinessRuntime()
    {
        for (const auto& behavior : _businessBehaviorNames)
            _orchestrator.unregisterBehavior(behavior);
        _businessBehaviorNames.clear();
        _businessContext.reset();
        _publishedBusinessRecords = 0;
    }

    rclcpp_action::GoalResponse onGoal(const rclcpp_action::GoalUUID&,
                                       std::shared_ptr<const Behavior::Goal> goal)
    {
        if (get_current_state().id() != lifecycle_msgs::msg::State::PRIMARY_STATE_ACTIVE ||
            goal->behavior.empty() || !_orchestrator.hasBehavior(goal->behavior))
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
        _activeExecutionId = goalId(goal->get_goal_id());
        PocoDDS::Robotics::BehaviorBlackboard blackboard;
        blackboard["parameters_json"] = goal->get_goal()->parameters_json;
        if (!_orchestrator.start(_activeExecutionId, goal->get_goal()->behavior,
                                 std::move(blackboard)))
        {
            auto result = std::make_shared<Behavior::Result>();
            result->success = false;
            result->detail = "behavior execution could not start";
            goal->abort(result);
            _activeExecutionId.clear();
            return;
        }
        _activeGoal = goal;
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
            command.joints.push_back({joint.name,
                                      static_cast<PocoDDS::Robotics::JointCommandMode>(joint.mode),
                                      joint.value});
        }
        const auto decision = _runtime->command(command);
        publishSafety(_runtime->emergencyStop(), decision.permitted, decision.reason);
    }

    void onEmergencyStop(const pdr_robot_msgs::srv::SetEmergencyStop::Request::SharedPtr request,
                         pdr_robot_msgs::srv::SetEmergencyStop::Response::SharedPtr response)
    {
        if (!_runtime)
        {
            response->accepted = false;
            response->state = "not configured";
            return;
        }
        if (!request->engaged &&
            get_current_state().id() != lifecycle_msgs::msg::State::PRIMARY_STATE_ACTIVE)
        {
            response->accepted = false;
            response->state = "release requires active lifecycle";
            publishSafety(true, false, response->state);
            return;
        }
        _runtime->setEmergencyStop(request->engaged, request->reason);
        response->accepted = true;
        response->state = request->engaged ? "engaged" : "released";
        publishSafety(request->engaged, false, response->state);
    }

    void onBackendFrame(const pdr_robot_msgs::msg::RobotFrame::SharedPtr message)
    {
        if (!_externalSimulator && !_externalHardware)
            return;
        PocoDDS::Robotics::RobotFrame frame;
        frame.state.monotonicTimeNanoseconds =
            rclcpp::Time(message->state.header.stamp).nanoseconds();
        frame.state.frameId = message->state.header.frame_id;
        frame.state.pose.position = {message->state.pose.position.x, message->state.pose.position.y,
                                     message->state.pose.position.z};
        frame.state.pose.orientation = {
            message->state.pose.orientation.x, message->state.pose.orientation.y,
            message->state.pose.orientation.z, message->state.pose.orientation.w};
        frame.state.twist.linear = {message->state.twist.linear.x, message->state.twist.linear.y,
                                    message->state.twist.linear.z};
        frame.state.twist.angular = {message->state.twist.angular.x, message->state.twist.angular.y,
                                     message->state.twist.angular.z};
        for (std::size_t index = 0; index < message->state.joints.name.size(); ++index)
        {
            PocoDDS::Robotics::JointState joint;
            joint.name = message->state.joints.name[index];
            if (index < message->state.joints.position.size())
                joint.position = message->state.joints.position[index];
            if (index < message->state.joints.velocity.size())
                joint.velocity = message->state.joints.velocity[index];
            if (index < message->state.joints.effort.size())
                joint.effort = message->state.joints.effort[index];
            frame.state.joints.push_back(std::move(joint));
        }
        for (const auto& input : message->sensors)
        {
            const auto type = sensorType(input.type);
            if (!type)
            {
                RCLCPP_WARN(get_logger(), "Ignoring sensor '%s' with invalid type %u",
                            input.name.c_str(), static_cast<unsigned int>(input.type));
                continue;
            }
            PocoDDS::Robotics::SensorSample sensor;
            sensor.name = input.name;
            sensor.type = *type;
            sensor.frameId = input.header.frame_id;
            sensor.monotonicTimeNanoseconds = rclcpp::Time(input.header.stamp).nanoseconds();
            sensor.encoding = input.encoding;
            sensor.shape = input.shape;
            sensor.values = input.values;
            sensor.data = input.data;
            frame.sensors.push_back(std::move(sensor));
        }
        for (const auto& input : message->contacts)
        {
            frame.contacts.push_back({input.first_body,
                                      input.second_body,
                                      {input.point.x, input.point.y, input.point.z},
                                      {input.normal.x, input.normal.y, input.normal.z},
                                      input.normal_force});
        }
        if (_externalHardware)
            _externalHardware->updateFrame(std::move(frame));
        else
            _externalSimulator->updateFrame(std::move(frame));
    }

    void tick()
    {
        if (!_runtime || _runtime->state() != PocoDDS::Robotics::LifecycleState::active)
            return;
        if (_runtimeFaulted)
            return;
        try
        {
            publishState(
                (_businessContext ? _businessContext->advance() : _runtime->step(_tickPeriod))
                    .state);
        }
        catch (const std::exception& exception)
        {
            _runtimeFaulted = true;
            _runtime->setEmergencyStop(true, "backend read failure");
            publishSafety(true, false, exception.what());
            abortActiveGoal(std::string("backend read failure: ") + exception.what());
            RCLCPP_ERROR(get_logger(), "Backend read failed: %s", exception.what());
            return;
        }
        catch (...)
        {
            _runtimeFaulted = true;
            _runtime->setEmergencyStop(true, "unknown backend read failure");
            publishSafety(true, false, "unknown backend read failure");
            abortActiveGoal("unknown backend read failure");
            RCLCPP_ERROR(get_logger(), "Backend read failed with an unknown exception");
            return;
        }
        tickAction();
        publishBusinessSteps();
    }

    void publishBusinessSteps()
    {
        if (!_businessContext || !_businessStepPublisher)
            return;
        const auto records = _businessContext->records();
        while (_publishedBusinessRecords < records.size())
        {
            const auto& record = records[_publishedBusinessRecords++];
            pdr_robot_msgs::msg::BusinessStep message;
            message.header.stamp = now();
            message.module = record.module;
            message.mission = record.mission;
            message.step = record.step;
            message.status = businessStepStatus(record.status);
            message.input = record.input;
            message.output = record.output;
            message.detail = record.detail;
            message.start_tick = record.startTick;
            message.finish_tick = record.finishTick;
            message.start_time_nanoseconds = record.startTimeNanoseconds;
            message.duration_nanoseconds = record.durationNanoseconds;
            _businessStepPublisher->publish(message);
        }
    }

    static std::uint8_t businessStepStatus(PocoDDS::Robotics::BusinessStepStatus status)
    {
        using CoreStatus = PocoDDS::Robotics::BusinessStepStatus;
        using Message = pdr_robot_msgs::msg::BusinessStep;
        switch (status)
        {
        case CoreStatus::succeeded:
            return Message::SUCCEEDED;
        case CoreStatus::failed:
            return Message::FAILED;
        case CoreStatus::canceled:
            return Message::CANCELED;
        }
        return Message::FAILED;
    }

    static std::optional<PocoDDS::Robotics::SensorType> sensorType(std::uint8_t type)
    {
        using Message = pdr_robot_msgs::msg::SensorSample;
        using Type = PocoDDS::Robotics::SensorType;
        switch (type)
        {
        case Message::IMU:
            return Type::imu;
        case Message::LIDAR:
            return Type::lidar;
        case Message::CAMERA:
            return Type::camera;
        case Message::DEPTH:
            return Type::depth;
        case Message::FORCE_TORQUE:
            return Type::forceTorque;
        case Message::CUSTOM:
            return Type::custom;
        default:
            return std::nullopt;
        }
    }

    void tickAction()
    {
        std::lock_guard<std::mutex> lock(_goalMutex);
        if (!_activeGoal)
            return;
        if (_activeGoal->is_canceling())
        {
            _orchestrator.cancel(_activeExecutionId);
            auto result = std::make_shared<Behavior::Result>();
            result->success = false;
            result->detail = "canceled";
            _activeGoal->canceled(result);
            _activeGoal.reset();
            _activeExecutionId.clear();
            return;
        }
        const auto snapshot = _orchestrator.tick(_activeExecutionId);
        if (!snapshot)
        {
            auto result = std::make_shared<Behavior::Result>();
            result->success = false;
            result->detail = "behavior execution disappeared";
            _activeGoal->abort(result);
            _activeGoal.reset();
            _activeExecutionId.clear();
            return;
        }
        auto feedback = std::make_shared<Behavior::Feedback>();
        feedback->progress =
            snapshot->status == PocoDDS::Robotics::BehaviorExecutionStatus::succeeded
                ? 1.0F
                : std::min(0.95F, static_cast<float>(snapshot->tickCount) * 0.1F);
        feedback->current_step = snapshot->detail;
        _activeGoal->publish_feedback(feedback);
        if (snapshot->status == PocoDDS::Robotics::BehaviorExecutionStatus::succeeded)
        {
            auto result = std::make_shared<Behavior::Result>();
            result->success = true;
            result->detail = snapshot->detail;
            _activeGoal->succeed(result);
            _activeGoal.reset();
            _activeExecutionId.clear();
        }
        else if (snapshot->status == PocoDDS::Robotics::BehaviorExecutionStatus::failed)
        {
            auto result = std::make_shared<Behavior::Result>();
            result->success = false;
            result->detail = snapshot->detail;
            _activeGoal->abort(result);
            _activeGoal.reset();
            _activeExecutionId.clear();
        }
    }

    void abortActiveGoal(const std::string& detail)
    {
        std::lock_guard<std::mutex> lock(_goalMutex);
        if (!_activeGoal)
            return;
        _orchestrator.cancel(_activeExecutionId);
        auto result = std::make_shared<Behavior::Result>();
        result->success = false;
        result->detail = detail;
        _activeGoal->abort(result);
        _activeGoal.reset();
        _activeExecutionId.clear();
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
        message.joints.header = message.header;
        for (const auto& joint : state.joints)
        {
            message.joints.name.push_back(joint.name);
            message.joints.position.push_back(joint.position);
            message.joints.velocity.push_back(joint.velocity);
            message.joints.effort.push_back(joint.effort);
        }
        message.simulated = _simulated;
        message.simulator_backend = _backendName;
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

    static std::string goalId(const rclcpp_action::GoalUUID& id)
    {
        std::ostringstream stream;
        stream << std::hex << std::setfill('0');
        for (const auto byte : id)
            stream << std::setw(2) << static_cast<unsigned int>(byte);
        return stream.str();
    }

    bool publishBackendCommand(const PocoDDS::Robotics::RobotCommand& command)
    {
        if (!_backendCommandPublisher)
            return false;
        pdr_robot_msgs::msg::RobotCommand message;
        message.header.stamp = now();
        message.sequence = command.sequence;
        message.base_velocity.linear.x = command.baseVelocity.linear.x;
        message.base_velocity.linear.y = command.baseVelocity.linear.y;
        message.base_velocity.linear.z = command.baseVelocity.linear.z;
        message.base_velocity.angular.x = command.baseVelocity.angular.x;
        message.base_velocity.angular.y = command.baseVelocity.angular.y;
        message.base_velocity.angular.z = command.baseVelocity.angular.z;
        for (const auto& joint : command.joints)
        {
            pdr_robot_msgs::msg::JointCommand output;
            output.name = joint.name;
            output.mode = static_cast<std::uint8_t>(joint.mode);
            output.value = joint.value;
            message.joints.push_back(std::move(output));
        }
        _backendCommandPublisher->publish(message);
        return true;
    }

    std::unique_ptr<PocoDDS::Robotics::RobotRuntime> _runtime;
    std::unique_ptr<PocoDDS::Robotics::BusinessContext> _businessContext;
    PocoDDS::Robotics::BusinessModuleRegistry _businessModules;
    PocoDDS::Robotics::BehaviorOrchestrator _orchestrator;
    std::vector<std::string> _businessBehaviorNames;
    std::size_t _publishedBusinessRecords{0};
    std::chrono::milliseconds _tickPeriod{20};
    std::string _backendName{"unconfigured"};
    bool _simulated{true};
    bool _runtimeFaulted{false};
    PocoDDS::Robotics::ExternalSimulator* _externalSimulator{nullptr};
    PocoDDS::Robotics::ExternalHardware* _externalHardware{nullptr};
    rclcpp_lifecycle::LifecyclePublisher<pdr_robot_msgs::msg::RobotState>::SharedPtr
        _statePublisher;
    rclcpp_lifecycle::LifecyclePublisher<pdr_robot_msgs::msg::SafetyState>::SharedPtr
        _safetyPublisher;
    rclcpp::Publisher<pdr_robot_msgs::msg::BusinessStep>::SharedPtr _businessStepPublisher;
    rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr _commandSubscription;
    rclcpp::Subscription<pdr_robot_msgs::msg::RobotCommand>::SharedPtr _robotCommandSubscription;
    rclcpp::Subscription<pdr_robot_msgs::msg::RobotFrame>::SharedPtr _backendFrameSubscription;
    rclcpp::Publisher<pdr_robot_msgs::msg::RobotCommand>::SharedPtr _backendCommandPublisher;
    rclcpp::Service<pdr_robot_msgs::srv::SetEmergencyStop>::SharedPtr _emergencyStopService;
    rclcpp_action::Server<Behavior>::SharedPtr _actionServer;
    rclcpp::TimerBase::SharedPtr _timer;
    std::mutex _goalMutex;
    std::shared_ptr<GoalHandle> _activeGoal;
    std::string _activeExecutionId;
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
