#include "PocoDDS/Membership/Membership.h"

#include <Poco/Exception.h>

#include <atomic>
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

using namespace PocoDDS::Membership;
using namespace std::chrono_literals;

namespace
{
Heartbeat heartbeat(std::string id, std::uint64_t incarnation,
                    std::uint64_t sequence)
{
    return {std::move(id), incarnation, sequence, "runtime", "dds://runtime",
            {"configuration", "health"}};
}

void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}
} // namespace

int main()
{
    try
    {
        auto now = std::chrono::steady_clock::time_point{};
        Registry registry({100ms, 500ms, 2}, [&] { return now; });

        const auto first = registry.observe(heartbeat("runtime-a", 10, 1));
        require(first.status == ObservationStatus::accepted && first.changed,
                "first heartbeat was not accepted");

        now += 90ms;
        const auto duplicate = registry.observe(heartbeat("runtime-a", 10, 1));
        require(duplicate.status == ObservationStatus::duplicate && !duplicate.changed,
                "duplicate heartbeat semantics are incorrect");
        now += 11ms;
        auto snapshot = registry.snapshot();
        require(snapshot.alive == 0 && snapshot.expired == 1,
                "duplicate heartbeat incorrectly extended TTL");

        require(registry.observe(heartbeat("runtime-a", 9, 99)).status ==
                    ObservationStatus::staleIncarnation,
                "old incarnation was accepted");
        require(registry.observe(heartbeat("runtime-a", 11, 1)).status ==
                    ObservationStatus::accepted,
                "replacement incarnation was rejected");
        require(registry.observe(heartbeat("runtime-a", 11, 0)).status ==
                    ObservationStatus::invalid,
                "zero sequence was accepted");
        require(registry.observe(heartbeat("runtime-a", 11, 2)).status ==
                    ObservationStatus::accepted,
                "new heartbeat sequence was rejected");
        require(registry.observe(heartbeat("runtime-a", 11, 1)).status ==
                    ObservationStatus::staleSequence,
                "backward heartbeat sequence was accepted");

        require(static_cast<bool>(registry.observe(heartbeat("runtime-b", 1, 1))),
                "second live member was rejected");
        require(registry.observe(heartbeat("runtime-c", 1, 1)).status ==
                    ObservationStatus::capacityExceeded,
                "live members were evicted at capacity");
        now += 101ms;
        require(static_cast<bool>(registry.observe(heartbeat("runtime-c", 1, 1))),
                "expired member was not evicted for a new live member");
        snapshot = registry.snapshot();
        require(snapshot.members.size() == 2 && snapshot.alive == 1 &&
                    snapshot.expired == 1,
                "capacity eviction snapshot is incorrect");

        require(!registry.leave("runtime-c", 2, 2),
                "leave from wrong incarnation removed live member");
        require(registry.leave("runtime-c", 1, 2),
                "matching incarnation could not leave");
        require(registry.observe(heartbeat("runtime-c", 1, 1)).status ==
                    ObservationStatus::staleSequence,
                "delayed heartbeat revived a gracefully departed member");

        Registry concurrent({5s, 5s, 4});
        std::vector<std::thread> workers;
        for (std::uint64_t sequence = 1; sequence <= 64; ++sequence)
            workers.emplace_back([&concurrent, sequence] {
                concurrent.observe(heartbeat("runtime-concurrent", 7, sequence));
            });
        for (auto& worker : workers) worker.join();
        const auto concurrentSnapshot = concurrent.snapshot();
        require(concurrentSnapshot.members.size() == 1 &&
                    concurrentSnapshot.members[0].heartbeat.sequence == 64,
                "concurrent observations did not retain the highest sequence");

        bool invalidOptions = false;
        try { Registry invalid({1ms, 1s, 1}); }
        catch (const Poco::InvalidArgumentException&) { invalidOptions = true; }
        require(invalidOptions, "invalid membership options were accepted");

        std::cout << "MEMBERSHIP_SMOKE_PASS generation=" << snapshot.generation
                  << " staleRejected=" << snapshot.statistics.staleRejected
                  << " expiredTransitions=" << snapshot.statistics.expiredTransitions
                  << '\n';
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "MEMBERSHIP_SMOKE_ERROR: " << error.what() << '\n';
        return 1;
    }
}
