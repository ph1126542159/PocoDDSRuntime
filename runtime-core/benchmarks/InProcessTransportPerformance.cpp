#include "PocoDDS/RuntimeCore/InProcessTransport.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <memory>
#include <numeric>
#include <vector>

#ifndef PDR_RUNTIME_CORE_INPROC_AVERAGE_BUDGET_US
#define PDR_RUNTIME_CORE_INPROC_AVERAGE_BUDGET_US 50.0
#endif
#ifndef PDR_RUNTIME_CORE_INPROC_P99_BUDGET_US
#define PDR_RUNTIME_CORE_INPROC_P99_BUDGET_US 200.0
#endif

int main()
{
    using Clock = std::chrono::steady_clock;
    using namespace PocoDDS::RuntimeCore;

    InProcessTransport transport;
    const TopicSpec topic{"pdr.performance.inproc", "pdr.performance.Message", "1",
                          Delivery::reliable, false};
    Message message;
    message.type = topic.messageType;
    message.schemaVersion = topic.schemaVersion;
    message.payload = std::make_shared<const Payload>(256, static_cast<std::uint8_t>(0x5a));
    std::size_t observed = 0;
    auto subscription =
        transport.subscribe(topic, [&observed](const TopicSpec&, const Message&) { ++observed; });

    constexpr std::size_t warmupIterations = 2000;
    constexpr std::size_t measuredIterations = 100000;
    for (std::size_t index = 0; index < warmupIterations; ++index)
        transport.publish(topic, message);

    std::vector<double> microseconds;
    microseconds.reserve(measuredIterations);
    for (std::size_t index = 0; index < measuredIterations; ++index)
    {
        const auto started = Clock::now();
        const auto result = transport.publish(topic, message);
        const auto finished = Clock::now();
        if (result.accepted != 1 || result.delivered != 1 || result.failed != 0 ||
            result.dropped != 0)
        {
            std::cerr << "PDR_RUNTIME_CORE_PERFORMANCE_FAIL reason=delivery-contract\n";
            return 2;
        }
        microseconds.push_back(
            std::chrono::duration<double, std::micro>(finished - started).count());
    }

    std::sort(microseconds.begin(), microseconds.end());
    const double average = std::accumulate(microseconds.begin(), microseconds.end(), 0.0) /
                           static_cast<double>(microseconds.size());
    const auto percentileIndex = static_cast<std::size_t>(0.99 * (microseconds.size() - 1));
    const double p99 = microseconds[percentileIndex];
    const double maximum = microseconds.back();
    const double throughput = 1000000.0 / average;
    const bool passed = average <= PDR_RUNTIME_CORE_INPROC_AVERAGE_BUDGET_US &&
                        p99 <= PDR_RUNTIME_CORE_INPROC_P99_BUDGET_US;
    if (observed != warmupIterations + measuredIterations)
    {
        std::cerr << "PDR_RUNTIME_CORE_PERFORMANCE_FAIL reason=observed-count\n";
        return 3;
    }

    std::cout << std::fixed << std::setprecision(3)
              << "PDR_RUNTIME_CORE_PERFORMANCE_RESULT iterations=" << measuredIterations
              << " payload_bytes=256 average_us=" << average << " p99_us=" << p99
              << " max_us=" << maximum << " throughput_messages_per_second=" << throughput
              << " average_budget_us=" << PDR_RUNTIME_CORE_INPROC_AVERAGE_BUDGET_US
              << " p99_budget_us=" << PDR_RUNTIME_CORE_INPROC_P99_BUDGET_US << '\n';
    if (!passed)
    {
        std::cerr << "PDR_RUNTIME_CORE_PERFORMANCE_FAIL reason=budget\n";
        return 1;
    }
    std::cout << "PDR_RUNTIME_CORE_PERFORMANCE_PASS\n";
    return 0;
}
