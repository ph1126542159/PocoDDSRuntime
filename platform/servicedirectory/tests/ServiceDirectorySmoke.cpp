#include "PocoDDS/ServiceDirectory/Directory.h"

#include <chrono>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace std::chrono_literals;
using namespace PocoDDS::ServiceDirectory;

namespace
{
Advertisement advertisement(std::string instance,
                            std::string runtime,
                            std::uint64_t incarnation,
                            std::uint64_t revision,
                            AdvertisedState state = AdvertisedState::ready)
{
    Advertisement value;
    value.serviceName = "orders.v1";
    value.instanceId = std::move(instance);
    value.runtimeId = std::move(runtime);
    value.runtimeIncarnation = incarnation;
    value.revision = revision;
    value.endpoint = "http://127.0.0.1:9000/orders";
    value.protocol = "http";
    value.zone = "zone-a";
    value.tags = {"json", "production"};
    value.state = state;
    return value;
}

void require(bool condition, const std::string& detail)
{
    if (!condition) throw std::runtime_error(detail);
}
} // namespace

int main()
{
    try
    {
        auto now = std::chrono::steady_clock::time_point{};
        Directory directory(
            {1000ms, 2000ms, 8, 4}, [&] { return now; });
        require(static_cast<bool>(directory.observe(
                    advertisement("orders-a", "runtime-a", 1, 1))),
                "first advertisement rejected");
        require(static_cast<bool>(directory.observe(
                    advertisement("orders-b", "runtime-b", 1, 1))),
                "second advertisement rejected");

        auto duplicate = directory.observe(
            advertisement("orders-a", "runtime-a", 1, 1));
        require(duplicate.status == ObservationStatus::duplicate,
                "duplicate was not detected");
        now += 1000ms;
        auto expired = directory.snapshot();
        require(expired.expired == 2,
                "duplicate advertisement incorrectly extended TTL");

        require(static_cast<bool>(directory.observe(
                    advertisement("orders-a", "runtime-a", 2, 1))),
                "new Runtime incarnation did not replace tombstone");
        auto stale = directory.observe(advertisement("orders-a", "runtime-a", 1, 99));
        require(stale.status == ObservationStatus::staleIncarnation,
                "old Runtime incarnation was accepted");
        auto conflict = directory.observe(
            advertisement("orders-a", "runtime-c", 3, 1));
        require(conflict.status == ObservationStatus::identityConflict,
                "cross-Runtime instance identity conflict was accepted");

        require(directory.withdraw("orders.v1", "orders-a", "runtime-a", 2, 2),
                "matching withdrawal failed");
        require(!directory.withdraw("orders.v1", "orders-a", "runtime-a", 2, 2),
                "withdrawal replay was accepted");
        require(static_cast<bool>(directory.observe(
                    advertisement("orders-a", "runtime-a", 3, 1))),
                "new incarnation did not recover withdrawn instance");

        require(static_cast<bool>(directory.observe(advertisement(
                    "orders-b", "runtime-b", 2, 1, AdvertisedState::draining))),
                "draining transition rejected");
        auto snapshot = directory.snapshot();
        require(snapshot.ready == 1 && snapshot.draining == 1,
                "ready/draining counts are incorrect");

        Router router;
        RouteRequest route;
        route.serviceName = "orders.v1";
        route.requiredTags = {"json"};
        auto selected = router.select(snapshot, route, [](const auto& value) {
            return value.runtimeId == "runtime-a" && value.runtimeIncarnation == 3;
        });
        require(selected && selected.instance->advertisement.instanceId == "orders-a",
                "membership eligibility did not filter route");

        require(static_cast<bool>(directory.observe(
                    advertisement("orders-c", "runtime-c", 1, 1))),
                "third instance rejected");
        snapshot = directory.snapshot();
        route.requiredTags.clear();
        route.policy = RoutingPolicy::roundRobin;
        const auto first = router.select(snapshot, route);
        const auto second = router.select(snapshot, route);
        require(first && second &&
                    first.instance->advertisement.instanceId !=
                        second.instance->advertisement.instanceId,
                "round-robin did not advance between ready instances");

        route.excludedInstances = {{
            first.instance->advertisement.instanceId,
            first.instance->advertisement.runtimeId,
            first.instance->advertisement.runtimeIncarnation}};
        const auto failover = router.select(snapshot, route);
        require(failover && failover.instance->advertisement.instanceId !=
                                first.instance->advertisement.instanceId,
                "explicit instance exclusion did not force failover");
        route.excludedInstances.clear();

        route.policy = RoutingPolicy::preferLocal;
        route.localRuntimeId = "runtime-c";
        selected = router.select(snapshot, route);
        require(selected && selected.instance->advertisement.runtimeId == "runtime-c",
                "prefer-local did not select a ready local instance");

        route.policy = RoutingPolicy::rendezvousHash;
        route.routingKey = "customer-42";
        const auto stableA = router.select(snapshot, route);
        const auto stableB = router.select(snapshot, route);
        require(stableA && stableB &&
                    stableA.instance->advertisement.instanceId ==
                        stableB.instance->advertisement.instanceId,
                "rendezvous route was not deterministic");

        route.routingKey.clear();
        require(router.select(snapshot, route).status ==
                    SelectionStatus::routingKeyRequired,
                "rendezvous accepted an empty routing key");

        std::cout << "SERVICE_DIRECTORY_PASS generation=" << snapshot.generation
                  << " ready=" << snapshot.ready
                  << " draining=" << snapshot.draining << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "SERVICE_DIRECTORY_ERROR: " << exception.what() << '\n';
        return 1;
    }
}
