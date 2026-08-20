#include "PocoDDS/Robotics/Business.h"
#include "PocoDDS/Robotics/BusinessPlugin.h"
#include "PocoDDS/Robotics/ReferenceBusinessModules.h"
#include "PocoDDS/Robotics/SimulationAdapter.h"

#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <exception>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

using namespace std::chrono_literals;
using namespace PocoDDS::Robotics;

namespace
{
struct Options
{
    std::string module{"all"};
    std::chrono::milliseconds period{10};
    std::size_t maximumSteps{5000};
    std::vector<std::string> plugins;
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
            std::cout << "Usage: pdr-business-sim [--module NAME] [--plugin PATH] "
                         "[--period-ms N] [--max-steps N]\n";
            std::exit(0);
        }
        if (index + 1 >= argc)
            throw std::invalid_argument("missing value for " + argument);
        if (argument == "--module")
            options.module = argv[++index];
        else if (argument == "--plugin")
            options.plugins.emplace_back(argv[++index]);
        else if (argument == "--period-ms")
            options.period =
                std::chrono::milliseconds(positiveNumber(argv[++index], "--period-ms"));
        else if (argument == "--max-steps")
            options.maximumSteps = positiveNumber(argv[++index], "--max-steps");
        else
            throw std::invalid_argument("unknown option: " + argument);
    }
    return options;
}

void require(bool condition, const std::string& message)
{
    if (!condition)
        throw std::runtime_error(message);
}

bool recordContains(const std::vector<BusinessStepRecord>& records, const std::string& step,
                    const std::string& text)
{
    for (const auto& record : records)
    {
        if (record.step == step && record.output.find(text) != std::string::npos)
            return true;
    }
    return false;
}

void printRecords(const std::vector<BusinessStepRecord>& records)
{
    for (const auto& record : records)
    {
        std::cout << "BUSINESS_STEP module=" << record.module << " mission=" << record.mission
                  << " step=" << record.step << " status=" << businessStepStatusName(record.status)
                  << " input=\"" << record.input << "\" output=\"" << record.output
                  << "\" ticks=" << (record.finishTick - record.startTick)
                  << " duration_ns=" << record.durationNanoseconds << '\n';
    }
}

void runScenario(const std::string& module, const Options& options)
{
    auto virtualNow = std::chrono::steady_clock::time_point{};
    SafetyLimits limits;
    limits.maximumLinearSpeed = 0.8;
    limits.maximumAngularSpeed = 0.6;
    limits.commandTimeout = 250ms;
    limits.joints.emplace("arm_joint", JointSafetyLimit{-1.2, 1.2, 1.0, 2.0});
    limits.joints.emplace("gripper_joint", JointSafetyLimit{-0.5, 0.5, 1.0, 1.0});

    RobotRuntime runtime(std::make_unique<InMemorySimulator>(), limits,
                         [&virtualNow] { return virtualNow; });
    runtime.setWorld("local://business-world");
    require(runtime.configure(), module + ": runtime configuration failed");
    require(runtime.activate(), module + ": runtime activation failed");
    Twist unsafeStartupCommand;
    unsafeStartupCommand.linear.x = 0.2;
    require(!runtime.commandVelocity(unsafeStartupCommand, virtualNow).permitted,
            module + ": startup interlock did not block motion");
    runtime.setEmergencyStop(false);

    BusinessContext context(runtime, options.period, [&virtualNow] { return virtualNow; });
    context.advance();
    virtualNow += options.period;
    if (module == "inspection")
        context.setSignal("inspection.anomaly", "true");

    BusinessModuleRegistry registry;
    require(registerReferenceBusinessModules(registry),
            "reference business module registration failed");
    for (const auto& plugin : options.plugins)
        require(registry.registerModule(BusinessPluginLoader::load(plugin)),
                "business plugin registration failed: " + plugin);
    BehaviorOrchestrator orchestrator;
    require(registry.install(module, orchestrator, context), module + ": module install failed");
    const auto missions = registry.missionNames(module);
    require(!missions.empty(), module + ": module does not expose a mission");
    const auto& mission = missions.front();
    const auto behavior = BusinessModuleRegistry::qualifiedBehaviorName(module, mission);
    const auto execution = module + "-execution";
    require(orchestrator.start(execution, behavior), module + ": mission start failed");

    bool dropoutInjected = false;
    bool watchdogStoppedMotion = module != "warehouse";
    for (std::size_t iteration = 0; iteration < options.maximumSteps; ++iteration)
    {
        const auto tick = context.tick();
        if (module == "warehouse" || module == "inspection")
        {
            const auto obstacleStart = module == "warehouse" ? 30U : 20U;
            const auto obstacleFinish = module == "warehouse" ? 45U : 32U;
            if (tick == obstacleStart)
                context.setSignal(module + ".obstacle", "true");
            else if (tick == obstacleFinish)
                context.setSignal(module + ".obstacle", "false");
        }

        if (module == "warehouse" && !dropoutInjected && tick >= 70)
        {
            dropoutInjected = true;
            RobotFrame settled;
            const auto dropoutCycles =
                static_cast<std::size_t>(250ms / options.period) + static_cast<std::size_t>(8);
            for (std::size_t cycle = 0; cycle < dropoutCycles; ++cycle)
            {
                const auto frame = context.advance();
                virtualNow += options.period;
                if (cycle + 3 == dropoutCycles)
                    settled = frame;
                if (cycle + 1 == dropoutCycles)
                {
                    watchdogStoppedMotion = std::abs(frame.state.pose.position.x -
                                                     settled.state.pose.position.x) < 1e-12;
                }
            }
        }

        const auto snapshot = orchestrator.tick(execution);
        if (!snapshot)
            throw std::runtime_error(module + ": mission disappeared");
        context.advance();
        virtualNow += options.period;
        if (snapshot->status == BehaviorExecutionStatus::succeeded)
            break;
        require(snapshot->status != BehaviorExecutionStatus::failed,
                module + ": mission behavior failed");
        require(snapshot->status != BehaviorExecutionStatus::canceled,
                module + ": mission was canceled");
        if (iteration + 1 == options.maximumSteps)
            throw std::runtime_error(module + ": mission exceeded maximum steps");
    }

    const auto snapshot = orchestrator.snapshot(execution);
    require(snapshot && snapshot->status == BehaviorExecutionStatus::succeeded,
            module + ": mission did not succeed");
    const auto records = context.records();
    require(!records.empty(), module + ": no business step records were produced");
    for (const auto& record : records)
        require(record.status == BusinessStepStatus::succeeded,
                module + ": business step did not succeed: " + record.step);

    const auto finalFrame = context.frame();
    if (module == "warehouse")
    {
        require(dropoutInjected && watchdogStoppedMotion,
                "warehouse: controller dropout watchdog did not stop motion");
        require(context.signalOr("warehouse.payload", "missing") == "released",
                "warehouse: payload was not released");
        require(finalFrame.state.pose.position.x >= 1.99,
                "warehouse: delivery target was not reached");
        require(recordContains(records, "navigate_to_pickup", "replans=1"),
                "warehouse: obstacle replan was not recorded");
    }
    else if (module == "inspection")
    {
        require(context.signalOr("inspection.report", "missing") == "anomaly_detected",
                "inspection: anomaly was not reported");
        require(std::abs(finalFrame.state.pose.position.x) <= 0.01,
                "inspection: robot did not return home");
        require(recordContains(records, "patrol_to_asset", "replans=1"),
                "inspection: obstacle replan was not recorded");
    }
    else if (module == "pick_place")
    {
        require(context.signalOr("pick_place.payload", "missing") == "released",
                "pick_place: payload was not released");
        require(recordContains(records, "open_gripper", "position=-0.200"),
                "pick_place: final gripper position was not reached");
    }

    runtime.setEmergencyStop(true, "business scenario complete");
    const auto stopped = context.advance();
    require(std::abs(stopped.state.pose.position.x - finalFrame.state.pose.position.x) < 1e-12 &&
                std::abs(stopped.state.pose.position.y - finalFrame.state.pose.position.y) < 1e-12,
            module + ": emergency stop did not hold position");
    runtime.shutdown();

    printRecords(records);
    std::cout << std::fixed << std::setprecision(6) << "PDR_BUSINESS_SIM_PASS module=" << module
              << " mission=" << mission << " ticks=" << context.tick()
              << " x=" << finalFrame.state.pose.position.x << " records=" << records.size()
              << " watchdog_stop=" << (watchdogStoppedMotion ? "true" : "false") << '\n';
}
} // namespace

int main(int argc, char** argv)
{
    try
    {
        const auto options = parseOptions(argc, argv);
        const std::vector<std::string> modules =
            options.module == "all"
                ? std::vector<std::string>{"warehouse", "inspection", "pick_place"}
                : std::vector<std::string>{options.module};
        for (const auto& module : modules)
            runScenario(module, options);
        std::cout << "PDR_BUSINESS_SIM_ALL_PASS modules=" << modules.size() << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "PDR_BUSINESS_SIM_FAIL: " << exception.what() << '\n';
        return 1;
    }
}
