#include "PocoDDS/Robotics/Action.h"
#include "PocoDDS/Robotics/Behavior.h"
#include "PocoDDS/Robotics/RobotRuntime.h"
#include "PocoDDS/Robotics/SimulationAdapter.h"

#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

using namespace std::chrono_literals;
using namespace PocoDDS::Robotics;

namespace
{
struct Options
{
    std::size_t steps{200};
    std::chrono::milliseconds period{5};
};

std::size_t positiveNumber(const char* text, const char* option)
{
    std::size_t consumed = 0;
    const auto value = std::stoull(text, &consumed);
    if (text[consumed] != '\0' || value == 0 || value > 1000000)
        throw std::invalid_argument(std::string(option) + " must be in [1, 1000000]");
    return static_cast<std::size_t>(value);
}

Options parseOptions(int argc, char** argv)
{
    Options options;
    for (int index = 1; index < argc; ++index)
    {
        const std::string argument = argv[index];
        if (argument == "--help")
        {
            std::cout << "Usage: pdr-robot-sim [--steps N] [--period-ms N]\n";
            std::exit(0);
        }
        if (index + 1 >= argc)
            throw std::invalid_argument("missing value for " + argument);
        if (argument == "--steps")
            options.steps = positiveNumber(argv[++index], "--steps");
        else if (argument == "--period-ms")
            options.period =
                std::chrono::milliseconds(positiveNumber(argv[++index], "--period-ms"));
        else
            throw std::invalid_argument("unknown option: " + argument);
    }
    return options;
}

void require(bool condition, const char* message)
{
    if (!condition)
        throw std::runtime_error(message);
}
} // namespace

int main(int argc, char** argv)
{
    try
    {
        const auto options = parseOptions(argc, argv);
        auto virtualNow = std::chrono::steady_clock::time_point{};

        SafetyLimits limits;
        limits.maximumLinearSpeed = 0.8;
        limits.maximumAngularSpeed = 0.6;
        limits.commandTimeout = 250ms;
        limits.joints.emplace("arm_joint", JointSafetyLimit{-1.2, 1.2, 1.0, 2.0});
        RobotRuntime runtime(std::make_unique<InMemorySimulator>(), limits,
                             [&virtualNow] { return virtualNow; });
        runtime.setWorld("local://warehouse");
        require(runtime.configure(), "runtime configuration failed");
        require(runtime.activate(), "runtime activation failed");

        Twist startupMotion;
        startupMotion.linear.x = 0.4;
        require(!runtime.commandVelocity(startupMotion, virtualNow).permitted,
                "startup safety interlock did not block motion");
        runtime.setEmergencyStop(false);

        std::size_t behaviorTicks = 0;
        BehaviorOrchestrator behaviors;
        require(behaviors.registerBehavior("local_patrol",
                                           [&behaviorTicks]
                                           {
                                               return std::make_unique<BehaviorTask>(
                                                   [&behaviorTicks](BehaviorBlackboard&)
                                                   {
                                                       ++behaviorTicks;
                                                       return behaviorTicks >= 3
                                                                  ? BehaviorStatus::succeeded
                                                                  : BehaviorStatus::running;
                                                   });
                                           }),
                "behavior registration failed");
        require(behaviors.start("local-mission", "local_patrol"), "behavior mission did not start");

        std::size_t simulatedSteps = 0;
        ActionCoordinator actions;
        require(actions.submit({"local-action", "drive_arc", {}},
                               [&simulatedSteps, &options](const ActionGoal&, bool canceled)
                               {
                                   if (canceled)
                                       return ActionFeedback{ActionStatus::canceled, 0.0,
                                                             "canceled"};
                                   const auto progress = static_cast<double>(simulatedSteps) /
                                                         static_cast<double>(options.steps);
                                   return ActionFeedback{simulatedSteps >= options.steps
                                                             ? ActionStatus::succeeded
                                                             : ActionStatus::running,
                                                         progress, "simulating"};
                               }),
                "action submission failed");

        RobotFrame frame;
        for (std::size_t step = 0; step < options.steps; ++step)
        {
            RobotCommand command;
            command.sequence = static_cast<std::uint64_t>(step + 1);
            command.baseVelocity.linear.x = 0.5;
            command.baseVelocity.angular.z = 0.2;
            const auto phase = static_cast<double>(step) / static_cast<double>(options.steps);
            command.joints.push_back(
                {"arm_joint", JointCommandMode::position, 0.5 * std::sin(phase * std::acos(-1.0))});
            require(runtime.command(command, virtualNow).permitted,
                    "simulation command was rejected");
            frame = runtime.step(options.period);
            ++simulatedSteps;
            virtualNow += options.period;
            behaviors.tick("local-mission");
            actions.tick("local-action");
        }

        const auto action = actions.feedback("local-action");
        const auto behavior = behaviors.snapshot("local-mission");
        require(action && action->status == ActionStatus::succeeded,
                "simulated action did not complete");
        require(behavior && behavior->status == BehaviorExecutionStatus::succeeded,
                "simulated behavior did not complete");
        require(!frame.state.joints.empty(), "simulated joint feedback is missing");
        require(runtime.backendHealth().ready, "simulation backend is not healthy");

        runtime.setEmergencyStop(true, "local simulation complete");
        const auto stopped = runtime.step(options.period);
        require(std::abs(stopped.state.pose.position.x - frame.state.pose.position.x) < 1e-12 &&
                    std::abs(stopped.state.pose.position.y - frame.state.pose.position.y) < 1e-12,
                "emergency stop did not hold the simulated robot");
        runtime.shutdown();

        std::cout << std::fixed << std::setprecision(6)
                  << "PDR_ROBOT_SIM_PASS steps=" << options.steps << " simulated_seconds="
                  << std::chrono::duration<double>(options.period * options.steps).count()
                  << " x=" << frame.state.pose.position.x << " y=" << frame.state.pose.position.y
                  << " joint=" << frame.state.joints.front().position << " stopped=true\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "PDR_ROBOT_SIM_FAIL: " << exception.what() << '\n';
        return 1;
    }
}
