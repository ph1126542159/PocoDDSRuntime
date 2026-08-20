#include "PocoDDS/Robotics/Action.h"
#include "PocoDDS/Robotics/Behavior.h"
#include "PocoDDS/Robotics/Business.h"
#include "PocoDDS/Robotics/ExternalHardware.h"
#include "PocoDDS/Robotics/MockHardware.h"
#include "PocoDDS/Robotics/RobotRuntime.h"
#include "PocoDDS/Robotics/SimulationAdapter.h"

#include <atomic>
#include <chrono>
#include <cmath>
#include <future>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <thread>
#include <vector>

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

class RejectingWriteBackend final : public RobotBackend
{
  public:
    std::string name() const override { return "rejecting-write"; }
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
    bool write(const RobotCommand&, std::chrono::nanoseconds) override { return false; }
    BackendHealth health() const override { return {_configured, _active, false, 0, 0, "test"}; }

  private:
    bool _configured{false};
    bool _active{false};
};

class SlowShutdownLifecycle final : public LifecycleComponent
{
  public:
    explicit SlowShutdownLifecycle(std::atomic<unsigned int>& shutdowns) : _shutdowns(shutdowns) {}

  protected:
    void onShutdown() noexcept override
    {
        ++_shutdowns;
        std::this_thread::sleep_for(20ms);
    }

  private:
    std::atomic<unsigned int>& _shutdowns;
};

class CustomTestBusinessModule final : public RobotBusinessModule
{
  public:
    std::string name() const override { return "custom_test"; }
    std::vector<std::string> missions() const override { return {"run"}; }
    std::unique_ptr<Behavior> createMission(const std::string& mission,
                                            BusinessContext& context) const override
    {
        if (mission != "run")
            return {};
        return makeTracedBusinessStep(
            context, name(), mission, "custom_logic", "input=test",
            std::make_unique<BehaviorTask>(
                [&context](BehaviorBlackboard&)
                {
                    context.setSignal("custom.result", "done");
                    return BehaviorStatus::succeeded;
                }),
            [&context] { return "result=" + context.signalOr("custom.result", "missing"); });
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
    expect(permitted.command.baseVelocity.linear.x == 1.0, "linear command was not limited");

    Twist diagonal;
    diagonal.linear.x = 1.0;
    diagonal.linear.y = 1.0;
    const auto diagonalDecision = runtime.commandVelocity(diagonal);
    expect(diagonalDecision.permitted, "finite diagonal velocity was rejected");
    expect(std::abs(std::hypot(diagonalDecision.command.baseVelocity.linear.x,
                               diagonalDecision.command.baseVelocity.linear.y) -
                    1.0) < 1e-12,
           "linear vector norm exceeded the safety limit");
    expect(runtime.commandVelocity(requested).permitted, "straight command restore failed");

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

    RobotCommand duplicateJoint;
    duplicateJoint.joints.push_back({"joint1", JointCommandMode::position, 0.1});
    duplicateJoint.joints.push_back({"joint1", JointCommandMode::velocity, 0.1});
    expect(!runtime.command(duplicateJoint).permitted, "duplicate joint command was accepted");

    auto expired = runtime.commandVelocity(requested, std::chrono::steady_clock::now() - 1s);
    expect(!expired.permitted, "watchdog must reject an expired command");
    expect(runtime.deactivate(), "deactivate failed");
    expect(runtime.cleanup(), "cleanup failed");
    runtime.shutdown();
    expect(runtime.state() == LifecycleState::finalized, "shutdown failed");
}

void testLifecycleConcurrencyAndLimitValidation()
{
    std::atomic<unsigned int> shutdowns{0};
    SlowShutdownLifecycle lifecycle(shutdowns);
    std::vector<std::future<void>> callers;
    callers.reserve(4);
    for (int index = 0; index < 4; ++index)
        callers.emplace_back(
            std::async(std::launch::async, [&lifecycle] { lifecycle.shutdown(); }));
    for (auto& caller : callers)
    {
        expect(caller.wait_for(1s) == std::future_status::ready,
               "concurrent lifecycle shutdown deadlocked");
        caller.get();
    }
    expect(shutdowns == 1, "shutdown callback ran more than once");
    expect(lifecycle.state() == LifecycleState::finalized, "concurrent shutdown did not finalize");

    SafetyLimits invalid;
    invalid.maximumLinearSpeed = std::numeric_limits<double>::quiet_NaN();
    bool rejectedInvalidLimits = false;
    try
    {
        SafetyBoundary boundary(invalid);
    }
    catch (const std::invalid_argument&)
    {
        rejectedInvalidLimits = true;
    }
    expect(rejectedInvalidLimits, "non-finite safety configuration was accepted");
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
    const auto running = actions.tick("goal-1");
    expect(running && running->status == ActionStatus::running, "action did not start");
    expect(actions.cancel("goal-1"), "action cancel request failed");
    const auto canceled = actions.tick("goal-1");
    expect(canceled && canceled->status == ActionStatus::canceled, "action was not canceled");

    expect(actions.submit({"goal-2", "failing", {}}, [](const ActionGoal&, bool) -> ActionFeedback
                          { throw std::runtime_error("injected executor failure"); }),
           "throwing action submit failed");
    const auto failed = actions.tick("goal-2");
    expect(failed && failed->status == ActionStatus::failed,
           "action executor exception did not become failed feedback");

    expect(actions.submit({"goal-3", "invalid-progress", {}},
                          [](const ActionGoal&, bool) {
                              return ActionFeedback{ActionStatus::running,
                                                    std::numeric_limits<double>::quiet_NaN(),
                                                    {}};
                          }),
           "invalid progress action submit failed");
    const auto invalidProgress = actions.tick("goal-3");
    expect(invalidProgress && invalidProgress->status == ActionStatus::failed,
           "non-finite action progress was accepted");
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
    expect(runtime.emergencyStop(), "backend write failure did not engage interlock");
    runtime.shutdown();

    auto readHardware = std::make_unique<MockHardware>(std::vector<std::string>{"joint1"});
    auto* readHardwareProbe = readHardware.get();
    RobotRuntime readRuntime(std::move(readHardware), limits);
    readRuntime.setBackendDescription("mock://read-failure");
    expect(readRuntime.configure(), "read failure runtime configure failed");
    expect(readRuntime.activate(), "read failure runtime activate failed");
    readRuntime.setEmergencyStop(false);
    readHardwareProbe->injectFault(MockHardwareFault::readFailure);
    bool readFailed = false;
    try
    {
        readRuntime.step(10ms);
    }
    catch (const std::runtime_error&)
    {
        readFailed = true;
    }
    expect(readFailed, "read failure was not propagated");
    expect(readRuntime.emergencyStop(), "backend read failure did not engage interlock");
    readRuntime.shutdown();

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

    RobotRuntime rejectingRuntime(std::make_unique<RejectingWriteBackend>());
    rejectingRuntime.setBackendDescription("test://reject-write");
    expect(rejectingRuntime.configure(), "rejecting backend configure failed");
    expect(rejectingRuntime.activate(), "rejecting backend activate failed");
    rejectingRuntime.setEmergencyStop(false);
    expect(!rejectingRuntime.command({}).permitted, "rejected backend write was hidden");
    expect(rejectingRuntime.emergencyStop(), "rejected backend write did not latch safety stop");
    rejectingRuntime.shutdown();
}

void testDeterministicPlanarSimulation()
{
    InMemorySimulator simulator;
    expect(simulator.connect("local://planar"), "local simulator connect failed");
    expect(!simulator.write({}, 10ms), "inactive simulator accepted a command");
    bool inactiveReadRejected = false;
    try
    {
        simulator.read(10ms);
    }
    catch (const std::logic_error&)
    {
        inactiveReadRejected = true;
    }
    expect(inactiveReadRejected, "inactive simulator returned feedback");
    expect(simulator.activate(), "local simulator activate failed");

    RobotCommand command;
    command.baseVelocity.linear.x = 1.0;
    command.baseVelocity.angular.z = std::acos(-1.0) / 2.0;
    expect(simulator.write(command, 1s), "local simulator command failed");
    const auto frame = simulator.read(1s);
    const auto expected = 2.0 / std::acos(-1.0);
    expect(std::abs(frame.state.pose.position.x - expected) < 1e-12,
           "planar simulator body-frame x integration failed");
    expect(std::abs(frame.state.pose.position.y - expected) < 1e-12,
           "planar simulator body-frame y integration failed");
    simulator.deactivate();

    auto now = std::chrono::steady_clock::time_point{};
    SafetyLimits watchdogLimits;
    watchdogLimits.commandTimeout = 100ms;
    RobotRuntime watchdogRuntime(std::make_unique<InMemorySimulator>(), watchdogLimits,
                                 [&now] { return now; });
    expect(watchdogRuntime.configure(), "watchdog runtime configure failed");
    expect(watchdogRuntime.activate(), "watchdog runtime activate failed");
    watchdogRuntime.setEmergencyStop(false);
    Twist velocity;
    velocity.linear.x = 0.5;
    expect(watchdogRuntime.commandVelocity(velocity, now).permitted,
           "watchdog runtime command failed");
    const auto moving = watchdogRuntime.step(100ms);
    now += 101ms;
    const auto stopped = watchdogRuntime.step(1s);
    expect(std::abs(stopped.state.pose.position.x - moving.state.pose.position.x) < 1e-12,
           "command watchdog did not stop a disconnected controller");
    watchdogRuntime.shutdown();

    now = std::chrono::steady_clock::time_point{};
    auto failingWatchdogHardware = std::make_unique<MockHardware>();
    auto* failingWatchdogProbe = failingWatchdogHardware.get();
    RobotRuntime failingWatchdogRuntime(std::move(failingWatchdogHardware), watchdogLimits,
                                        [&now] { return now; });
    failingWatchdogRuntime.setBackendDescription("mock://watchdog-failure");
    expect(failingWatchdogRuntime.configure(), "failing watchdog configure failed");
    expect(failingWatchdogRuntime.activate(), "failing watchdog activate failed");
    failingWatchdogRuntime.setEmergencyStop(false);
    expect(failingWatchdogRuntime.commandVelocity(velocity, now).permitted,
           "failing watchdog initial command failed");
    failingWatchdogProbe->injectFault(MockHardwareFault::writeFailure);
    now += 101ms;
    bool watchdogStopFailed = false;
    try
    {
        failingWatchdogRuntime.step(1ms);
    }
    catch (const std::runtime_error&)
    {
        watchdogStopFailed = true;
    }
    expect(watchdogStopFailed, "watchdog stop rejection was hidden");
    expect(failingWatchdogRuntime.emergencyStop(),
           "watchdog stop rejection did not latch emergency stop");
    failingWatchdogRuntime.shutdown();
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
        [](BehaviorBlackboard& board) {
            board["localized"] = "true";
            return BehaviorStatus::succeeded;
        }));
    sequence.add(std::make_unique<BehaviorTask>(
        [](BehaviorBlackboard& board)
        {
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

    bool timeoutHalted = false;
    BehaviorTimeout haltingTimeout(
        std::make_unique<BehaviorTask>([](BehaviorBlackboard&) { return BehaviorStatus::running; },
                                       [&timeoutHalted] { timeoutHalted = true; }),
        100ms, [&now] { return now; });
    expect(haltingTimeout.tick(blackboard) == BehaviorStatus::running,
           "halting timeout child did not start");
    now += 101ms;
    expect(haltingTimeout.tick(blackboard) == BehaviorStatus::failed && timeoutHalted,
           "timed-out behavior was not halted");

    bool parallelHalted = false;
    BehaviorParallel parallel(1);
    parallel.add(std::make_unique<BehaviorTask>([](BehaviorBlackboard&)
                                                { return BehaviorStatus::succeeded; }));
    parallel.add(std::make_unique<BehaviorTask>([](BehaviorBlackboard&)
                                                { return BehaviorStatus::running; },
                                                [&parallelHalted] { parallelHalted = true; }));
    expect(parallel.tick(blackboard) == BehaviorStatus::succeeded,
           "parallel success threshold failed");
    expect(parallelHalted, "parallel completion did not halt unfinished work");

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
    const auto canceledExecution = orchestrator.snapshot("execution-2");
    expect(canceledExecution && canceledExecution->status == BehaviorExecutionStatus::canceled,
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

void testReplaceableBusinessModule()
{
    auto now = std::chrono::steady_clock::time_point{};
    RobotRuntime runtime(std::make_unique<InMemorySimulator>(), SafetyLimits{},
                         [&now] { return now; });
    expect(runtime.configure(), "business runtime configure failed");
    expect(runtime.activate(), "business runtime activate failed");
    runtime.setEmergencyStop(false);
    BusinessContext context(runtime, 10ms, [&now] { return now; });
    BusinessModuleRegistry registry;
    expect(registry.registerModule(std::make_shared<CustomTestBusinessModule>()),
           "custom business module registration failed");
    expect(!registry.registerModule(std::make_shared<CustomTestBusinessModule>()),
           "duplicate business module was accepted");
    expect(registry.contains("custom_test"), "custom business module is missing");

    BehaviorOrchestrator orchestrator;
    expect(registry.install("custom_test", orchestrator, context),
           "custom business module install failed");
    const auto behavior = BusinessModuleRegistry::qualifiedBehaviorName("custom_test", "run");
    expect(orchestrator.start("custom-execution", behavior),
           "custom business mission did not start");
    const auto completed = orchestrator.tick("custom-execution");
    expect(completed && completed->status == BehaviorExecutionStatus::succeeded,
           "custom business mission did not succeed");
    const auto records = context.records();
    expect(records.size() == 1 && records.front().step == "custom_logic" &&
               records.front().output == "result=done",
           "custom business trace is incomplete");
    expect(orchestrator.unregisterBehavior(behavior), "custom business behavior unregister failed");
    expect(!orchestrator.hasBehavior(behavior), "custom business behavior remained registered");

    expect(orchestrator.registerBehavior(
               "custom/cancel",
               [&context]
               {
                   return makeTracedBusinessStep(
                       context, "custom", "cancel", "wait", "request=wait",
                       std::make_unique<BehaviorTask>([](BehaviorBlackboard&)
                                                      { return BehaviorStatus::running; }));
               }),
           "cancel trace behavior registration failed");
    expect(orchestrator.start("cancel-execution", "custom/cancel"),
           "cancel trace behavior did not start");
    const auto running = orchestrator.tick("cancel-execution");
    expect(running && running->status == BehaviorExecutionStatus::running,
           "cancel trace behavior did not run");
    expect(orchestrator.cancel("cancel-execution"), "cancel trace behavior did not cancel");
    const auto canceledRecords = context.records();
    expect(canceledRecords.size() == 2 &&
               canceledRecords.back().status == BusinessStepStatus::canceled,
           "business cancellation was not traced");

    expect(orchestrator.registerBehavior(
               "custom/fail",
               [&context]
               {
                   return makeTracedBusinessStep(
                       context, "custom", "fail", "reject", "request=invalid",
                       std::make_unique<BehaviorTask>([](BehaviorBlackboard&)
                                                      { return BehaviorStatus::failed; }));
               }),
           "failure trace behavior registration failed");
    expect(orchestrator.start("failure-execution", "custom/fail"),
           "failure trace behavior did not start");
    const auto failed = orchestrator.tick("failure-execution");
    expect(failed && failed->status == BehaviorExecutionStatus::failed,
           "failure trace behavior did not fail");
    const auto failedRecords = context.records();
    expect(failedRecords.size() == 3 && failedRecords.back().status == BusinessStepStatus::failed,
           "business failure was not traced");

    expect(orchestrator.registerBehavior("throwing-factory", []() -> std::unique_ptr<Behavior>
                                         { throw std::runtime_error("injected factory failure"); }),
           "throwing behavior factory registration failed");
    expect(!orchestrator.start("throwing-execution", "throwing-factory"),
           "behavior factory exception escaped start");
    runtime.shutdown();
}
} // namespace

int main()
{
    try
    {
        testLifecycleSimulationAndSafety();
        testLifecycleConcurrencyAndLimitValidation();
        testActionCancellation();
        testHardwareBackendAndFaults();
        testDeterministicPlanarSimulation();
        testExternalSimulationBoundary();
        testExternalHardwareBoundary();
        testBehaviorSequence();
        testBehaviorOrchestration();
        testReplaceableBusinessModule();
        std::cout << "ROBOTICS_RUNTIME_TEST_PASS\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "ROBOTICS_RUNTIME_TEST_FAIL: " << exception.what() << '\n';
        return 1;
    }
}
