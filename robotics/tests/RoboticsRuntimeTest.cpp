#include "PocoDDS/Robotics/Action.h"
#include "PocoDDS/Robotics/Behavior.h"
#include "PocoDDS/Robotics/RobotRuntime.h"

#include <chrono>
#include <cmath>
#include <iostream>
#include <memory>
#include <stdexcept>

using namespace std::chrono_literals;
using namespace PocoDDS::Robotics;

namespace
{
class StateAwareLifecycle final : public LifecycleComponent
{
protected:
    bool onConfigure() override
    {
        return state() == LifecycleState::unconfigured;
    }
};

void expect(bool condition, const char* message)
{
    if (!condition)
        throw std::runtime_error(message);
}

void testLifecycleSimulationAndSafety()
{
    StateAwareLifecycle stateAware;
    expect(stateAware.configure(), "lifecycle callback could not inspect state");
    stateAware.shutdown();

    SafetyLimits limits;
    limits.maximumLinearSpeed = 1.0;
    limits.maximumAngularSpeed = 0.5;
    limits.commandTimeout = 100ms;
    limits.joints.emplace("joint1", JointSafetyLimit{-1.0, 1.0, 2.0, 3.0});
    RobotRuntime runtime(std::make_unique<InMemorySimulator>(), limits);

    expect(runtime.configure(), "configure failed");
    expect(runtime.activate(), "activate failed");

    Twist requested;
    requested.linear.x = 4.0;
    auto blocked = runtime.commandVelocity(requested);
    expect(!blocked.permitted, "startup interlock must block motion");

    runtime.setEmergencyStop(false);
    auto permitted = runtime.commandVelocity(requested);
    expect(permitted.permitted, "released interlock should permit motion");
    expect(permitted.command.baseVelocity.linear.x == 1.0,
           "linear command was not limited");

    const auto frame = runtime.step(1s);
    expect(std::abs(frame.state.pose.position.x - 1.0) < 1e-9,
           "simulation did not integrate the limited command");

    RobotCommand unknownJoint;
    unknownJoint.joints.push_back({"unbounded_joint", JointCommandMode::effort, 1.0});
    expect(!runtime.command(unknownJoint).permitted,
           "an unbounded joint command must fail closed");

    RobotCommand boundedJoint;
    boundedJoint.joints.push_back({"joint1", JointCommandMode::position, 4.0});
    const auto jointDecision = runtime.command(boundedJoint);
    expect(jointDecision.permitted, "a bounded joint command should be permitted");
    expect(jointDecision.command.joints.front().value == 1.0,
           "joint position was not clamped");
    const auto jointFrame = runtime.step(10ms);
    expect(jointFrame.state.joints.front().position == 1.0,
           "simulation did not apply the joint command");

    auto expired = runtime.commandVelocity(requested,
        std::chrono::steady_clock::now() - 1s);
    expect(!expired.permitted, "watchdog must reject an expired command");
    expect(runtime.deactivate(), "deactivate failed");
    expect(runtime.cleanup(), "cleanup failed");
    runtime.shutdown();
    expect(runtime.state() == LifecycleState::finalized, "shutdown failed");
}

void testActionCancellation()
{
    ActionCoordinator actions;
    expect(actions.submit({"goal-1", "navigate", "x=1"},
        [](const ActionGoal&, bool canceled) {
            return ActionFeedback{canceled ? ActionStatus::canceled : ActionStatus::running,
                                  canceled ? 0.25 : 0.1,
                                  canceled ? "stopped" : "moving"};
        }), "action submit failed");
    expect(actions.tick("goal-1")->status == ActionStatus::running,
           "action did not start");
    expect(actions.cancel("goal-1"), "action cancel request failed");
    expect(actions.tick("goal-1")->status == ActionStatus::canceled,
           "action was not canceled");
}

void testBehaviorSequence()
{
    BehaviorBlackboard blackboard;
    BehaviorSequence sequence;
    sequence.add(std::make_unique<BehaviorTask>([](BehaviorBlackboard& board) {
        board["localized"] = "true";
        return BehaviorStatus::succeeded;
    }));
    sequence.add(std::make_unique<BehaviorTask>([](BehaviorBlackboard& board) {
        return board["localized"] == "true" ? BehaviorStatus::succeeded
                                             : BehaviorStatus::failed;
    }));
    expect(sequence.tick(blackboard) == BehaviorStatus::succeeded,
           "behavior sequence failed");

    BehaviorSelector selector;
    selector.add(std::make_unique<BehaviorTask>([](BehaviorBlackboard&) {
        return BehaviorStatus::failed;
    }));
    selector.add(std::make_unique<BehaviorTask>([](BehaviorBlackboard&) {
        return BehaviorStatus::succeeded;
    }));
    expect(selector.tick(blackboard) == BehaviorStatus::succeeded,
           "behavior selector fallback failed");
}
} // namespace

int main()
{
    try
    {
        testLifecycleSimulationAndSafety();
        testActionCancellation();
        testBehaviorSequence();
        std::cout << "ROBOTICS_RUNTIME_TEST_PASS\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "ROBOTICS_RUNTIME_TEST_FAIL: " << exception.what() << '\n';
        return 1;
    }
}
