#include "PocoDDS/Robotics/ReferenceBusinessModules.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <utility>

using namespace std::chrono_literals;

namespace PocoDDS::Robotics
{
namespace
{
std::string number(double value)
{
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(3) << value;
    return stream.str();
}

std::unique_ptr<Behavior>
makeImmediateStep(BusinessContext& context, const std::string& module, const std::string& mission,
                  std::string step, std::string input,
                  std::function<BehaviorStatus(BehaviorBlackboard&)> callback,
                  BusinessOutputProvider output)
{
    return makeTracedBusinessStep(context, module, mission, std::move(step), std::move(input),
                                  std::make_unique<BehaviorTask>(std::move(callback)),
                                  std::move(output));
}

std::unique_ptr<Behavior> makeDriveStep(BusinessContext& context, const std::string& module,
                                        const std::string& mission, std::string step,
                                        double targetX, double speed,
                                        const std::string& obstacleSignal)
{
    struct State
    {
        std::size_t replans{0};
        bool obstacleLatched{false};
    };
    auto state = std::make_shared<State>();
    auto task = std::make_unique<BehaviorTask>(
        [&context, targetX, speed, obstacleSignal, state](BehaviorBlackboard& blackboard)
        {
            const auto obstacle = context.signalOr(obstacleSignal, "false") == "true";
            if (obstacle)
            {
                if (!state->obstacleLatched)
                {
                    ++state->replans;
                    state->obstacleLatched = true;
                }
                blackboard["current_step"] = "waiting_for_obstacle_clearance";
                return context.commandVelocity({}).permitted ? BehaviorStatus::running
                                                             : BehaviorStatus::failed;
            }
            state->obstacleLatched = false;
            const auto x = context.frame().state.pose.position.x;
            const auto reached = speed >= 0.0 ? x >= targetX - 0.005 : x <= targetX + 0.005;
            if (reached)
            {
                blackboard["current_step"] = "target_reached";
                return context.commandVelocity({}).permitted ? BehaviorStatus::succeeded
                                                             : BehaviorStatus::failed;
            }
            Twist command;
            command.linear.x = speed;
            blackboard["current_step"] = "driving";
            return context.commandVelocity(command).permitted ? BehaviorStatus::running
                                                              : BehaviorStatus::failed;
        },
        [&context]
        {
            try
            {
                context.commandVelocity({});
            }
            catch (...)
            {
                return;
            }
        });
    auto timeout = std::make_unique<BehaviorTimeout>(std::move(task), 30s,
                                                     [&context] { return context.now(); });
    const auto input = "target_x=" + number(targetX) + ",speed=" + number(speed) +
                       ",obstacle_signal=" + obstacleSignal;
    return makeTracedBusinessStep(context, module, mission, std::move(step), input,
                                  std::move(timeout),
                                  [&context, state]
                                  {
                                      return "x=" + number(context.frame().state.pose.position.x) +
                                             ",replans=" + std::to_string(state->replans);
                                  });
}

std::unique_ptr<Behavior> makeJointStep(BusinessContext& context, const std::string& module,
                                        const std::string& mission, std::string step,
                                        const std::string& joint, double target,
                                        const std::string& resultSignal,
                                        const std::string& resultValue)
{
    struct State
    {
        bool commanded{false};
    };
    auto state = std::make_shared<State>();
    auto task = std::make_unique<BehaviorTask>(
        [&context, joint, target, resultSignal, resultValue, state](BehaviorBlackboard& blackboard)
        {
            if (state->commanded)
            {
                const auto frame = context.frame();
                const auto found =
                    std::find_if(frame.state.joints.begin(), frame.state.joints.end(),
                                 [&joint](const JointState& value) { return value.name == joint; });
                if (found != frame.state.joints.end() && std::abs(found->position - target) < 1e-6)
                {
                    if (!resultSignal.empty())
                        context.setSignal(resultSignal, resultValue);
                    blackboard["current_step"] = "joint_target_reached";
                    return BehaviorStatus::succeeded;
                }
            }
            RobotCommand command;
            command.joints.push_back({joint, JointCommandMode::position, target});
            state->commanded = true;
            blackboard["current_step"] = "moving_joint";
            return context.command(std::move(command)).permitted ? BehaviorStatus::running
                                                                 : BehaviorStatus::failed;
        });
    auto timeout = std::make_unique<BehaviorTimeout>(std::move(task), 5s,
                                                     [&context] { return context.now(); });
    return makeTracedBusinessStep(
        context, module, mission, std::move(step), "joint=" + joint + ",target=" + number(target),
        std::move(timeout),
        [&context, joint, resultSignal]
        {
            const auto frame = context.frame();
            const auto found =
                std::find_if(frame.state.joints.begin(), frame.state.joints.end(),
                             [&joint](const JointState& value) { return value.name == joint; });
            const auto position = found == frame.state.joints.end() ? std::string("missing")
                                                                    : number(found->position);
            return "position=" + position +
                   (resultSignal.empty() ? std::string{}
                                         : ",signal=" + context.signalOr(resultSignal, "missing"));
        });
}

class WarehouseBusinessModule final : public RobotBusinessModule
{
  public:
    std::string name() const override { return "warehouse"; }
    std::vector<std::string> missions() const override { return {"deliver"}; }

    std::unique_ptr<Behavior> createMission(const std::string& mission,
                                            BusinessContext& context) const override
    {
        if (mission != "deliver")
            return {};
        auto sequence = std::make_unique<BehaviorSequence>();
        sequence->add(makeImmediateStep(
            context, name(), mission, "localize", "map=warehouse_map",
            [&context](BehaviorBlackboard& blackboard)
            {
                context.setSignal("warehouse.localized", "true");
                blackboard["current_step"] = "localized";
                return BehaviorStatus::succeeded;
            },
            [&context]
            { return "localized=" + context.signalOr("warehouse.localized", "false"); }));
        sequence->add(makeDriveStep(context, name(), mission, "navigate_to_pickup", 1.0, 0.5,
                                    "warehouse.obstacle"));
        sequence->add(makeJointStep(context, name(), mission, "pick_payload", "arm_joint", 0.8,
                                    "warehouse.payload", "attached"));
        sequence->add(makeDriveStep(context, name(), mission, "navigate_to_dropoff", 2.0, 0.5,
                                    "warehouse.obstacle"));
        sequence->add(makeJointStep(context, name(), mission, "release_payload", "arm_joint", -0.2,
                                    "warehouse.payload", "released"));
        return sequence;
    }
};

class InspectionBusinessModule final : public RobotBusinessModule
{
  public:
    std::string name() const override { return "inspection"; }
    std::vector<std::string> missions() const override { return {"patrol"}; }

    std::unique_ptr<Behavior> createMission(const std::string& mission,
                                            BusinessContext& context) const override
    {
        if (mission != "patrol")
            return {};
        auto sequence = std::make_unique<BehaviorSequence>();
        sequence->add(makeImmediateStep(
            context, name(), mission, "sensor_self_check", "sensors=imu,lidar,camera",
            [&context](BehaviorBlackboard& blackboard)
            {
                context.setSignal("inspection.sensors", "ready");
                blackboard["current_step"] = "sensors_ready";
                return BehaviorStatus::succeeded;
            },
            [&context] { return "sensors=" + context.signalOr("inspection.sensors", "missing"); }));
        sequence->add(makeDriveStep(context, name(), mission, "patrol_to_asset", 0.8, 0.4,
                                    "inspection.obstacle"));
        sequence->add(makeImmediateStep(
            context, name(), mission, "analyze_asset", "camera=thermal,lidar=clearance",
            [&context](BehaviorBlackboard& blackboard)
            {
                const auto anomaly = context.signalOr("inspection.anomaly", "false");
                context.setSignal("inspection.report",
                                  anomaly == "true" ? "anomaly_detected" : "normal");
                blackboard["current_step"] = "asset_analyzed";
                return BehaviorStatus::succeeded;
            },
            [&context] { return "report=" + context.signalOr("inspection.report", "missing"); }));
        sequence->add(makeDriveStep(context, name(), mission, "return_home", 0.0, -0.4,
                                    "inspection.obstacle"));
        return sequence;
    }
};

class PickPlaceBusinessModule final : public RobotBusinessModule
{
  public:
    std::string name() const override { return "pick_place"; }
    std::vector<std::string> missions() const override { return {"transfer"}; }

    std::unique_ptr<Behavior> createMission(const std::string& mission,
                                            BusinessContext& context) const override
    {
        if (mission != "transfer")
            return {};
        auto sequence = std::make_unique<BehaviorSequence>();
        sequence->add(
            makeJointStep(context, name(), mission, "approach_object", "arm_joint", 0.6, {}, {}));
        sequence->add(makeJointStep(context, name(), mission, "close_gripper", "gripper_joint", 0.3,
                                    "pick_place.payload", "grasped"));
        sequence->add(
            makeJointStep(context, name(), mission, "move_to_place", "arm_joint", -0.4, {}, {}));
        sequence->add(makeJointStep(context, name(), mission, "open_gripper", "gripper_joint", -0.2,
                                    "pick_place.payload", "released"));
        return sequence;
    }
};
} // namespace

std::shared_ptr<RobotBusinessModule> createWarehouseBusinessModule()
{
    return std::make_shared<WarehouseBusinessModule>();
}

std::shared_ptr<RobotBusinessModule> createInspectionBusinessModule()
{
    return std::make_shared<InspectionBusinessModule>();
}

std::shared_ptr<RobotBusinessModule> createPickPlaceBusinessModule()
{
    return std::make_shared<PickPlaceBusinessModule>();
}

bool registerReferenceBusinessModules(BusinessModuleRegistry& registry)
{
    return registry.registerModule(createWarehouseBusinessModule()) &&
           registry.registerModule(createInspectionBusinessModule()) &&
           registry.registerModule(createPickPlaceBusinessModule());
}
} // namespace PocoDDS::Robotics
