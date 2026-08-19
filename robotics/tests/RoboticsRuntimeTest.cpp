#include "PocoDDS/Robotics/Action.h"
#include "PocoDDS/Robotics/Behavior.h"
#include "PocoDDS/Robotics/ExternalHardware.h"
#include "PocoDDS/Robotics/MockHardware.h"
#include "PocoDDS/Robotics/RobotRuntime.h"
#include "PocoDDS/Robotics/SimulationAdapter.h"

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
    bool onConfigure() override { return state() == LifecycleState::unconfigured; }
};

class ThrowingStopBackend final : public RobotBackend
{
  public:
    std::string name() const override { return "throwing-stop"; }
    BackendKind kind() const noexcept override { return BackendKind::hardware; }
    bool configure(const std::string&) override
    {
        _configured = true;
        return true;
    }
    bool activate() override
    {
        _active = _configured;
        return _active;
    }
    void deactivate() noexcept override { _active = false; }
    void reset() override
    {
        _configured = false;
        _active = false;
    }
    RobotFrame read(std::chrono::nanoseconds) override { return {}; }
    bool write(const RobotCommand&, std::chrono::nanoseconds) override
    {
        throw std::runtime_error("injected stop failure");
    }
    BackendHealth health() const override { return {_configured, _active, _active, 0, 0, "test"}; }

  private:
    bool _configured{false};
    bool _active{false};
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
    expect(permitted.command.baseVelocity.linear.x == 1.0, "linear command was not limited");

    const auto frame = runtime.step(1s);
    expect(std::abs(frame.state.pose.position.x - 1.0) < 1e-9,
           "simulation did not integrate the limited command");

    RobotCommand unknownJoint;
    unknownJoint.joints.push_back({"unbounded_joint", JointCommandMode::effort, 1.0});
    expect(!runtime.command(unknownJoint).permitted, "an unbounded joint command must fail closed");

    RobotCommand boundedJoint;
    boundedJoint.joints.push_back({"joint1", JointCommandMode::position, 4.0});
    const auto jointDecision = runtime.command(boundedJoint);
    expect(jointDecision.permitted, "a bounded joint command should be permitted");
    expect(jointDecision.command.joints.front().value == 1.0, "joint position was not clamped");
    const auto jointFrame = runtime.step(10ms);
    expect(jointFrame.state.joints.front().position == 1.0,
           "simulation did not apply the joint command");

    auto expired = runtime.commandVelocity(requested, std::chrono::steady_clock::now() - 1s);
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
                          [](const ActionGoal&, bool canceled)
                          {
                              return ActionFeedback{
                                  canceled ? ActionStatus::canceled : ActionStatus::running,
                                  canceled ? 0.25 : 0.1, canceled ? "stopped" : "moving"};
                          }),
           "action submit failed");
    expect(actions.tick("goal-1")->status == ActionStatus::running, "action did not start");
    expect(actions.cancel("goal-1"), "action cancel request failed");
    expect(actions.tick("goal-1")->status == ActionStatus::canceled, "action was not canceled");
}

void testHardwareBackendAndFaults()
{
    SafetyLimits limits;
    limits.joints.emplace("joint1", JointSafetyLimit{-1.0, 1.0, 2.0, 3.0});
    auto hardware = std::make_unique<MockHardware>(std::vector<std::string>{"joint1"});
    auto* hardwareProbe = hardware.get();
    RobotRuntime runtime(std::move(hardware), limits);
    runtime.setBackendDescription("mock://robot");
    expect(runtime.configure(), "mock hardware configure failed");
    expect(runtime.backendHealth().configured, "hardware health was not configured");
    expect(runtime.activate(), "mock hardware activate failed");
    runtime.setEmergencyStop(false);

    RobotCommand command;
    command.joints.push_back({"joint1", JointCommandMode::position, 0.75});
    expect(runtime.command(command).permitted, "mock hardware rejected bounded command");
    const auto frame = runtime.step(10ms);
    expect(frame.state.joints.front().position == 0.75,
           "mock hardware did not mirror joint position");

    hardwareProbe->injectFault(MockHardwareFault::writeFailure);
    expect(!runtime.command(command).permitted, "write failure was not propagated");
    hardwareProbe->injectFault(MockHardwareFault::readFailure);
    bool readFailed = false;
    try
    {
        runtime.step(10ms);
    }
    catch (const std::runtime_error&)
    {
        readFailed = true;
    }
    expect(readFailed, "read failure was not propagated");
    expect(runtime.emergencyStop(), "backend read failure did not engage interlock");
    runtime.shutdown();

    MockHardware atomicHardware({"joint1"});
    expect(atomicHardware.configure("mock://atomic"), "atomic hardware configure failed");
    expect(atomicHardware.activate(), "atomic hardware activate failed");
    RobotCommand initial;
    initial.joints.push_back({"joint1", JointCommandMode::position, 0.5});
    expect(atomicHardware.write(initial, 1ms), "initial hardware write failed");
    RobotCommand partial;
    partial.joints.push_back({"joint1", JointCommandMode::position, 0.9});
    partial.joints.push_back({"unknown", JointCommandMode::position, 0.1});
    expect(!atomicHardware.write(partial, 1ms), "invalid batch was accepted");
    expect(atomicHardware.read(1ms).state.joints.front().position == 0.5,
           "invalid batch partially changed hardware state");

    RobotRuntime throwingRuntime(std::make_unique<ThrowingStopBackend>());
    throwingRuntime.setBackendDescription("test://throwing-stop");
    expect(throwingRuntime.configure(), "throwing backend configure failed");
    expect(throwingRuntime.activate(), "throwing backend activate failed");
    throwingRuntime.setEmergencyStop(true, "test stop");
    expect(throwingRuntime.emergencyStop(), "stop exception escaped the safety latch");
    throwingRuntime.shutdown();
}

void testExternalSimulationBoundary()
{
    auto now = std::chrono::steady_clock::time_point{};
    std::size_t commands = 0;
    ExternalSimulator simulator(
        "topic-simulator",
        [&commands](const RobotCommand&)
        {
            ++commands;
            return true;
        },
        100ms, [&now] { return now; });
    expect(simulator.connect("world"), "external simulator connect failed");
    expect(!simulator.activate(), "external simulator activated without feedback");
    RobotFrame feedback;
    feedback.state.frameId = "world";
    simulator.updateFrame(feedback);
    expect(simulator.activate(), "external simulator did not activate with feedback");
    expect(simulator.write({}, 10ms), "external simulator command failed");
    expect(commands == 1, "external simulator command sink was not called");
    expect(simulator.read(10ms).state.frameId == "world",
           "external simulator feedback was not returned");
    now += 101ms;
    bool timedOut = false;
    try
    {
        simulator.read(10ms);
    }
    catch (const std::runtime_error&)
    {
        timedOut = true;
    }
    expect(timedOut, "external simulator stale feedback was not rejected");
}

void testExternalHardwareBoundary()
{
    auto now = std::chrono::steady_clock::time_point{};
    ExternalHardware hardware(
        "can-gateway", [](const RobotCommand&) { return true; }, 100ms, [&now] { return now; });
    expect(hardware.kind() == BackendKind::hardware,
           "external hardware reported the wrong backend kind");
    expect(hardware.configure("can://can0"), "external hardware configure failed");
    expect(!hardware.activate(), "external hardware activated without feedback");
    hardware.updateFrame({});
    expect(hardware.activate(), "external hardware did not activate with feedback");
    expect(hardware.write({}, 10ms), "external hardware command failed");
    expect(hardware.read(10ms).state.frameId == "base_link",
           "external hardware feedback was not returned");
    now += 101ms;
    bool timedOut = false;
    try
    {
        hardware.read(10ms);
    }
    catch (const std::runtime_error&)
    {
        timedOut = true;
    }
    expect(timedOut, "external hardware stale feedback was not rejected");
}

void testBehaviorSequence()
{
    BehaviorBlackboard blackboard;
    BehaviorSequence sequence;
    sequence.add(std::make_unique<BehaviorTask>(
        [](BehaviorBlackboard& board)
        {
            board["localized"] = "true";
            return BehaviorStatus::succeeded;
        }));
    sequence.add(std::make_unique<BehaviorTask>(
        [](BehaviorBlackboard& board) {
            return board["localized"] == "true" ? BehaviorStatus::succeeded
                                                : BehaviorStatus::failed;
        }));
    expect(sequence.tick(blackboard) == BehaviorStatus::succeeded, "behavior sequence failed");

    BehaviorSelector selector;
    selector.add(
        std::make_unique<BehaviorTask>([](BehaviorBlackboard&) { return BehaviorStatus::failed; }));
    selector.add(std::make_unique<BehaviorTask>([](BehaviorBlackboard&)
                                                { return BehaviorStatus::succeeded; }));
    expect(selector.tick(blackboard) == BehaviorStatus::succeeded,
           "behavior selector fallback failed");
}

void testBehaviorOrchestration()
{
    BehaviorBlackboard blackboard;
    std::size_t attempts = 0;
    BehaviorRetry retry(std::make_unique<BehaviorTask>(
                            [&attempts](BehaviorBlackboard&)
                            {
                                ++attempts;
                                return attempts < 2 ? BehaviorStatus::failed
                                                    : BehaviorStatus::succeeded;
                            }),
                        2);
    expect(retry.tick(blackboard) == BehaviorStatus::running,
           "retry did not schedule another attempt");
    expect(retry.tick(blackboard) == BehaviorStatus::succeeded,
           "retry did not succeed on the second attempt");

    auto now = std::chrono::steady_clock::time_point{};
    BehaviorTimeout timeout(
        std::make_unique<BehaviorTask>([](BehaviorBlackboard&) { return BehaviorStatus::running; }),
        100ms, [&now] { return now; });
    expect(timeout.tick(blackboard) == BehaviorStatus::running, "timeout child did not start");
    now += 101ms;
    expect(timeout.tick(blackboard) == BehaviorStatus::failed,
           "timeout did not fail an overdue behavior");

    BehaviorParallel parallel(1);
    parallel.add(std::make_unique<BehaviorTask>([](BehaviorBlackboard&)
                                                { return BehaviorStatus::succeeded; }));
    parallel.add(std::make_unique<BehaviorTask>([](BehaviorBlackboard&)
                                                { return BehaviorStatus::running; }));
    expect(parallel.tick(blackboard) == BehaviorStatus::succeeded,
           "parallel success threshold failed");

    BehaviorOrchestrator orchestrator;
    expect(orchestrator.registerBehavior("inspect",
                                         []
                                         {
                                             auto sequence = std::make_unique<BehaviorSequence>();
                                             sequence->add(std::make_unique<BehaviorTask>(
                                                 [](BehaviorBlackboard& board)
                                                 {
                                                     board["step"] = "localized";
                                                     return BehaviorStatus::succeeded;
                                                 }));
                                             sequence->add(std::make_unique<BehaviorTask>(
                                                 [](BehaviorBlackboard&)
                                                 { return BehaviorStatus::succeeded; }));
                                             return sequence;
                                         }),
           "behavior registration failed");
    expect(orchestrator.start("execution-1", "inspect"), "behavior execution did not start");
    const auto completed = orchestrator.tick("execution-1");
    expect(completed && completed->status == BehaviorExecutionStatus::succeeded,
           "behavior execution did not complete");

    expect(orchestrator.registerBehavior("wait",
                                         []
                                         {
                                             return std::make_unique<BehaviorTask>(
                                                 [](BehaviorBlackboard&)
                                                 { return BehaviorStatus::running; });
                                         }),
           "wait behavior registration failed");
    expect(orchestrator.start("execution-2", "wait"), "wait behavior did not start");
    expect(orchestrator.cancel("execution-2"), "behavior cancellation failed");
    expect(orchestrator.snapshot("execution-2")->status == BehaviorExecutionStatus::canceled,
           "behavior was not marked canceled");

    bool halted = false;
    expect(orchestrator.registerBehavior("haltable",
                                         [&halted]
                                         {
                                             return std::make_unique<BehaviorTask>(
                                                 [](BehaviorBlackboard&)
                                                 { return BehaviorStatus::running; },
                                                 [&halted] { halted = true; });
                                         }),
           "haltable behavior registration failed");
    expect(orchestrator.start("execution-3", "haltable"), "haltable behavior did not start");
    expect(orchestrator.cancel("execution-3"), "haltable behavior cancel failed");
    expect(halted, "behavior cancellation did not halt the active task");
}
} // namespace

int main()
{
    try
    {
        testLifecycleSimulationAndSafety();
        testActionCancellation();
        testHardwareBackendAndFaults();
        testExternalSimulationBoundary();
        testExternalHardwareBoundary();
        testBehaviorSequence();
        testBehaviorOrchestration();
        std::cout << "ROBOTICS_RUNTIME_TEST_PASS\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "ROBOTICS_RUNTIME_TEST_FAIL: " << exception.what() << '\n';
        return 1;
    }
}
