#include "PocoDDS/ServiceClient/Client.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <future>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using namespace std::chrono_literals;
using namespace PocoDDS::ServiceClient;
using namespace PocoDDS::ServiceDirectory;

namespace
{
void require(bool condition, const std::string& detail)
{
    if (!condition) throw std::runtime_error(detail);
}

Advertisement advertisement(std::string instance, std::string runtime,
                            std::uint64_t incarnation = 1)
{
    Advertisement value;
    value.serviceName = "orders.v1";
    value.instanceId = std::move(instance);
    value.runtimeId = std::move(runtime);
    value.runtimeIncarnation = incarnation;
    value.revision = 1;
    value.endpoint = "loopback://" + value.instanceId;
    value.protocol = "loopback";
    value.tags = {"json"};
    return value;
}
} // namespace

int main()
{
    try
    {
        auto now = std::chrono::steady_clock::time_point{};
        Directory directory;
        require(static_cast<bool>(directory.observe(
                    advertisement("orders-a", "runtime-a"))),
                "orders-a advertisement rejected");
        require(static_cast<bool>(directory.observe(
                    advertisement("orders-b", "runtime-b"))),
                "orders-b advertisement rejected");
        Router router;
        const auto route = [&](const RouteRequest& request) {
            return router.select(directory.snapshot(), request);
        };

        Policy policy;
        policy.maximumAttempts = 3;
        policy.timeout = 1000ms;
        policy.initialBackoff = 10ms;
        policy.maximumBackoff = 20ms;
        policy.circuitFailureThreshold = 1;
        policy.circuitResetTimeout = 100ms;
        policy.circuitIdleRetention = 1000ms;
        Client client(policy, route, [&] { return now; },
                      [&](std::chrono::milliseconds delay) { now += delay; });

        InvocationRequest request;
        request.route.serviceName = "orders.v1";
        request.operation = "create-order";
        request.idempotencyKey = "request-1";
        std::vector<std::string> invoked;
        const auto failover = client.invoke(request, [&](const AttemptContext& context) {
            invoked.push_back(context.instance.advertisement.instanceId);
            if (context.attempt == 1)
                return AttemptResult::retryable("transport", "connection reset");
            return AttemptResult::success({0x4f, 0x4b});
        });
        require(failover && failover.attempts == 2 &&
                    failover.payload == std::vector<std::uint8_t>({0x4f, 0x4b}),
                "idempotent failover did not succeed");
        require(invoked.size() == 2 && invoked[0] == "orders-a" &&
                    invoked[1] == "orders-b",
                "retry did not fail over to a different instance");

        auto state = client.snapshot();
        const auto openA = std::find_if(
            state.circuits.begin(), state.circuits.end(), [](const auto& circuit) {
                return circuit.instanceId == "orders-a" &&
                       circuit.state == CircuitState::open;
            });
        require(openA != state.circuits.end(),
                "failed instance circuit did not open");
        require(state.calls == 1 && state.succeeded == 1 &&
                    state.attempts == 2 && state.retries == 1,
                "client statistics are incorrect after failover");

        require(static_cast<bool>(directory.observe(
                    advertisement("orders-a", "runtime-a", 2))),
                "restarted orders-a incarnation was rejected");
        InvocationRequest restarted = request;
        restarted.route.policy = RoutingPolicy::preferLocal;
        restarted.route.localRuntimeId = "runtime-a";
        restarted.idempotencyKey = "restart-1";
        const auto freshIncarnation = client.invoke(
            restarted, [](const AttemptContext& context) {
                return context.instance.advertisement.runtimeIncarnation == 2
                           ? AttemptResult::success()
                           : AttemptResult::permanent(
                                 "stale-incarnation",
                                 "old Runtime incarnation was selected");
            });
        require(freshIncarnation &&
                    freshIncarnation.instance->advertisement.runtimeIncarnation == 2,
                "old incarnation circuit incorrectly blocked restarted Runtime");

        InvocationRequest unsafe = request;
        unsafe.idempotencyKey.clear();
        unsafe.idempotent = false;
        unsafe.operation = "charge-card";
        unsafe.route.policy = RoutingPolicy::preferLocal;
        unsafe.route.localRuntimeId = "runtime-b";
        std::size_t unsafeAttempts = 0;
        const auto suppressed = client.invoke(unsafe, [&](const AttemptContext&) {
            ++unsafeAttempts;
            return AttemptResult::retryable("timeout", "outcome unknown");
        });
        require(suppressed.status == InvocationStatus::failed &&
                    unsafeAttempts == 1 &&
                    suppressed.detail.find("retry suppressed") != std::string::npos,
                "non-idempotent retry was not suppressed");

        now += 101ms;
        InvocationRequest probe = request;
        probe.route.policy = RoutingPolicy::preferLocal;
        probe.route.localRuntimeId = "runtime-b";
        probe.idempotencyKey = "probe-1";
        const auto recovered = client.invoke(probe, [](const AttemptContext& context) {
            if (context.instance.advertisement.instanceId != "orders-b")
                return AttemptResult::permanent(
                    "wrong-instance", "half-open probe was not preferred");
            return AttemptResult::success();
        });
        require(recovered && recovered.instance->advertisement.instanceId == "orders-b",
                "half-open circuit did not admit a recovery probe");
        state = client.snapshot();
        const auto closedB = std::find_if(
            state.circuits.begin(), state.circuits.end(), [](const auto& circuit) {
                return circuit.instanceId == "orders-b" &&
                       circuit.state == CircuitState::closed;
            });
        require(closedB != state.circuits.end(),
                "successful half-open probe did not close the circuit");

        InvocationRequest deadline = request;
        deadline.idempotencyKey = "deadline-1";
        const auto expired = client.invoke(deadline, [&](const AttemptContext&) {
            now += 1001ms;
            return AttemptResult::success();
        });
        require(expired.status == InvocationStatus::deadlineExceeded,
                "late success incorrectly escaped the total deadline");

        InvocationRequest missing = request;
        missing.route.serviceName = "missing.v1";
        const auto noRoute = client.invoke(missing, [](const AttemptContext&) {
            return AttemptResult::success();
        });
        require(noRoute.status == InvocationStatus::noRoute,
                "missing service was not reported as no-route");

        const auto cancelled = client.invoke(
            request, [](const AttemptContext&) {
                return AttemptResult::success();
            }, [] { return true; });
        require(cancelled.status == InvocationStatus::cancelled &&
                    cancelled.attempts == 0,
                "pre-routing cancellation did not prevent invocation");

        Client throwingRoute(policy,
            [](const RouteRequest&) -> RouteResult {
                throw std::runtime_error("directory unavailable");
            }, [&] { return now; },
            [&](std::chrono::milliseconds delay) { now += delay; });
        const auto routeFailure = throwingRoute.invoke(
            request, [](const AttemptContext&) {
                return AttemptResult::success();
            });
        require(routeFailure.status == InvocationStatus::noRoute &&
                    routeFailure.code == "route-failure" &&
                    routeFailure.detail == "directory unavailable",
                "route callback exception escaped the client boundary");

        Policy bounded = policy;
        bounded.maximumAttempts = 1;
        bounded.maximumCircuitEntries = 1;
        Client capacityClient(bounded, route, [&] { return now; },
                              [&](std::chrono::milliseconds delay) { now += delay; });
        InvocationRequest localA = request;
        localA.route.policy = RoutingPolicy::preferLocal;
        localA.route.localRuntimeId = "runtime-a";
        const auto failedA = capacityClient.invoke(
            localA, [](const AttemptContext&) {
                return AttemptResult::retryable("transport", "offline");
            });
        require(failedA.status == InvocationStatus::failed,
                "capacity setup failure was not recorded");
        InvocationRequest localB = localA;
        localB.route.localRuntimeId = "runtime-b";
        const auto boundedResult = capacityClient.invoke(
            localB, [](const AttemptContext&) {
                return AttemptResult::success();
            });
        require(boundedResult.status ==
                    InvocationStatus::circuitCapacityExceeded,
                "bounded circuit registry silently evicted an open circuit");

        Directory probeDirectory;
        require(static_cast<bool>(probeDirectory.observe(
                    advertisement("probe-a", "probe-runtime"))),
                "probe advertisement rejected");
        Router probeRouter;
        std::atomic<long long> probeClock{0};
        Policy probePolicy = policy;
        probePolicy.maximumAttempts = 1;
        Client concurrentProbe(
            probePolicy,
            [&](const RouteRequest& value) {
                return probeRouter.select(probeDirectory.snapshot(), value);
            },
            [&] {
                return std::chrono::steady_clock::time_point{
                    std::chrono::milliseconds{probeClock.load()}};
            }, [](std::chrono::milliseconds) {});
        InvocationRequest probeRequest;
        probeRequest.route.serviceName = "orders.v1";
        probeRequest.operation = "probe";
        probeRequest.idempotent = true;
        require(concurrentProbe.invoke(
                    probeRequest, [](const AttemptContext&) {
                        return AttemptResult::retryable("offline", "offline");
                    }).status == InvocationStatus::failed,
                "concurrent probe setup did not open the circuit");
        probeClock = 101;

        std::promise<void> enteredPromise;
        auto entered = enteredPromise.get_future();
        std::promise<void> releasePromise;
        auto release = releasePromise.get_future();
        InvocationResult firstProbe;
        std::thread probeThread([&] {
            firstProbe = concurrentProbe.invoke(
                probeRequest, [&](const AttemptContext&) {
                    enteredPromise.set_value();
                    release.wait();
                    return AttemptResult::success();
                });
        });
        if (entered.wait_for(2s) != std::future_status::ready)
        {
            releasePromise.set_value();
            probeThread.join();
            throw std::runtime_error("half-open probe did not start");
        }
        const auto competingProbe = concurrentProbe.invoke(
            probeRequest, [](const AttemptContext&) {
                return AttemptResult::success();
            });
        releasePromise.set_value();
        probeThread.join();
        require(firstProbe &&
                    competingProbe.status == InvocationStatus::circuitOpen,
                "half-open circuit admitted more than one concurrent probe");

        std::cout << "SERVICE_CLIENT_PASS calls=" << state.calls
                  << " attempts=" << state.attempts
                  << " retries=" << state.retries
                  << " circuits=" << state.circuits.size() << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "SERVICE_CLIENT_ERROR: " << exception.what() << '\n';
        return 1;
    }
}
