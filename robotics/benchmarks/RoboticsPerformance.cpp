#include "PocoDDS/Robotics/RobotRuntime.h"
#include "PocoDDS/Robotics/SimulationAdapter.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <memory>
#include <numeric>
#include <vector>

#ifndef PDR_ROBOTICS_STEP_AVERAGE_BUDGET_US
#define PDR_ROBOTICS_STEP_AVERAGE_BUDGET_US 500.0
#endif
#ifndef PDR_ROBOTICS_STEP_P99_BUDGET_US
#define PDR_ROBOTICS_STEP_P99_BUDGET_US 2000.0
#endif

int main()
{
    using Clock = std::chrono::steady_clock;
    using namespace std::chrono_literals;
    using PocoDDS::Robotics::InMemorySimulator;
    using PocoDDS::Robotics::RobotRuntime;
    using PocoDDS::Robotics::Twist;

    RobotRuntime runtime(std::make_unique<InMemorySimulator>());
    runtime.setWorld("performance-baseline");
    if (!runtime.configure() || !runtime.activate())
    {
        std::cerr << "PDR_ROBOTICS_PERFORMANCE_FAIL reason=runtime-startup\n";
        return 2;
    }
    runtime.setEmergencyStop(false);
    Twist command;
    command.linear.x = 0.25;
    if (!runtime.commandVelocity(command).permitted)
    {
        std::cerr << "PDR_ROBOTICS_PERFORMANCE_FAIL reason=command-rejected\n";
        return 3;
    }

    constexpr std::size_t warmupIterations = 500;
    constexpr std::size_t measuredIterations = 5000;
    for (std::size_t index = 0; index < warmupIterations; ++index)
        runtime.step(5ms);

    std::vector<double> microseconds;
    microseconds.reserve(measuredIterations);
    for (std::size_t index = 0; index < measuredIterations; ++index)
    {
        const auto started = Clock::now();
        runtime.step(5ms);
        const auto finished = Clock::now();
        microseconds.push_back(
            std::chrono::duration<double, std::micro>(finished - started).count());
    }
    runtime.shutdown();

    std::sort(microseconds.begin(), microseconds.end());
    const double average = std::accumulate(microseconds.begin(), microseconds.end(), 0.0) /
                           static_cast<double>(microseconds.size());
    const auto percentileIndex = static_cast<std::size_t>(0.99 * (microseconds.size() - 1));
    const double p99 = microseconds[percentileIndex];
    const double maximum = microseconds.back();
    const double throughput = 1000000.0 / average;
    const bool passed = average <= PDR_ROBOTICS_STEP_AVERAGE_BUDGET_US &&
                        p99 <= PDR_ROBOTICS_STEP_P99_BUDGET_US;

    std::cout << std::fixed << std::setprecision(3)
              << "PDR_ROBOTICS_PERFORMANCE_RESULT iterations=" << measuredIterations
              << " average_us=" << average << " p99_us=" << p99 << " max_us=" << maximum
              << " throughput_steps_per_second=" << throughput
              << " average_budget_us=" << PDR_ROBOTICS_STEP_AVERAGE_BUDGET_US
              << " p99_budget_us=" << PDR_ROBOTICS_STEP_P99_BUDGET_US << '\n';
    if (!passed)
    {
        std::cerr << "PDR_ROBOTICS_PERFORMANCE_FAIL\n";
        return 1;
    }
    std::cout << "PDR_ROBOTICS_PERFORMANCE_PASS\n";
    return 0;
}
