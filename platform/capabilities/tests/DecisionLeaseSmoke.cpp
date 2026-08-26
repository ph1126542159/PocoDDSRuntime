#include "PocoDDS/Capabilities/AuthorizedTransport.h"
#include "PocoDDS/Capabilities/DecisionLease.h"
#include "PocoDDS/Capabilities/PolicyEngine.h"
#include "PocoDDS/RuntimeCore/InProcessTransport.h"

#include <Poco/Exception.h>

#include <atomic>
#include <future>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

using namespace PocoDDS::Capabilities;
using namespace PocoDDS::RuntimeCore;

namespace
{
std::vector<Rule> allowedPolicy()
{
    return {{"telemetry-publish", Effect::allow, "sensor.*", ResourceKind::topic,
             "telemetry.*", {Action::publish, Action::subscribe}}};
}
} // namespace

int main()
{
    try
    {
        std::atomic<Poco::UInt64> auditWrites{0};
        std::atomic<Poco::Int64> now{1000000};
        std::atomic<bool> healthy{true};
        PolicyEngine engine(allowedPolicy(), 256,
            [&](const AuditRecord&) { ++auditWrites; });
        DecisionLeaseOptions options;
        options.durationMilliseconds = 10;
        options.maximumUses = 3;
        options.capacity = 2;
        auto lease = std::make_shared<DecisionLeaseAuthorizer>(
            [&](const Request& request) { return engine.decide(request); },
            [&] { return engine.snapshot(); }, options,
            [&] { return healthy.load(); }, [&] { return now.load(); });

        const Request first{"sensor.one", ResourceKind::topic,
                            "telemetry.temperature", Action::publish};
        for (int use = 0; use < 3; ++use)
            if (!lease->authorize(first).allowed)
                throw std::runtime_error("leased allow was unexpectedly denied");
        if (auditWrites != 1 || lease->snapshot().hits != 2 ||
            lease->snapshot().entries != 0)
            throw std::runtime_error("lease use budget did not bound audit reuse");
        static_cast<void>(lease->authorize(first));
        if (auditWrites != 2 || lease->snapshot().issued != 2)
            throw std::runtime_error("exhausted lease was not reauthorized");

        const Request denied{"intruder", ResourceKind::topic,
                             "telemetry.temperature", Action::publish};
        if (lease->authorize(denied).allowed || lease->authorize(denied).allowed ||
            auditWrites != 4 || lease->snapshot().denied != 2)
            throw std::runtime_error("denied decisions were cached or not audited");

        now += 10001;
        static_cast<void>(lease->authorize(first));
        if (auditWrites != 5 || lease->snapshot().expired != 1)
            throw std::runtime_error("expired lease did not force reauthorization");

        const Request second{"sensor.two", ResourceKind::topic,
                             "telemetry.humidity", Action::publish};
        const Request third{"sensor.three", ResourceKind::topic,
                            "telemetry.pressure", Action::publish};
        static_cast<void>(lease->authorize(second));
        static_cast<void>(lease->authorize(third));
        if (lease->snapshot().entries != 2 || lease->snapshot().evicted == 0)
            throw std::runtime_error("lease capacity did not evict an old entry");

        const auto beforeReplacement = engine.snapshot();
        static_cast<void>(engine.replace(
            {"deny-all", "operator", beforeReplacement.generation, {}}));
        if (lease->authorize(third).allowed)
            throw std::runtime_error("generation change did not revoke cached allow");
        const auto revoked = lease->snapshot();
        if (revoked.policyGeneration != engine.snapshot().generation ||
            revoked.invalidated == 0 || revoked.entries != 0)
            throw std::runtime_error("generation invalidation statistics are incomplete");

        const auto deniedGeneration = engine.snapshot();
        static_cast<void>(engine.replace(
            {"restore-allow", "operator", deniedGeneration.generation, allowedPolicy()}));
        if (!lease->authorize(first).allowed)
            throw std::runtime_error("restored policy did not issue a new lease");
        healthy = false;
        bool unhealthyClosed = false;
        try { static_cast<void>(lease->authorize(first)); }
        catch (const Poco::IllegalStateException&) { unhealthyClosed = true; }
        if (!unhealthyClosed)
            throw std::runtime_error("cached lease bypassed unhealthy persistence state");
        healthy = true;
        if (!lease->authorize(first).allowed)
            throw std::runtime_error("healthy lease did not resume after test recovery");

        std::atomic<Poco::UInt64> crossingGeneration{1};
        std::atomic<int> crossingCalls{0};
        DecisionLeaseAuthorizer crossingLease(
            [&](const Request&) {
                const auto generation = crossingGeneration.load();
                if (++crossingCalls == 1) crossingGeneration = 2;
                return Decision{true, "CAPABILITY_ALLOWED", "crossing", "test",
                                generation, "digest-" + std::to_string(generation)};
            },
            [&] {
                const auto generation = crossingGeneration.load();
                return PolicySnapshot{generation,
                    "digest-" + std::to_string(generation), 1, Effect::deny};
            });
        const auto stableCrossing = crossingLease.authorize(first);
        if (stableCrossing.policyGeneration != 2 || crossingCalls != 2)
            throw std::runtime_error("cross-generation lease issuance was not retried");

        PolicyEngine unavailableAudit(allowedPolicy(), 16, [](const AuditRecord&) {
            throw Poco::IOException("durable lease audit unavailable");
        });
        DecisionLeaseAuthorizer failedLease(
            [&](const Request& request) { return unavailableAudit.decide(request); },
            [&] { return unavailableAudit.snapshot(); });
        bool auditClosed = false;
        try { static_cast<void>(failedLease.authorize(first)); }
        catch (const Poco::IOException&) { auditClosed = true; }
        if (!auditClosed || failedLease.snapshot().entries != 0)
            throw std::runtime_error("lease was created without durable authorization audit");

        auto delegate = std::make_shared<InProcessTransport>();
        AuthorizedTransport transport("sensor.one", delegate, lease);
        TopicSpec topic{"telemetry.temperature", "sample", "1",
                        Delivery::bestEffort, false};
        std::size_t deliveries = 0;
        auto subscription = transport.subscribe(topic,
            [&](const TopicSpec&, const Message&) { ++deliveries; });
        Message message{"sample", "1", std::make_shared<const Payload>(Payload{1}), {}, {}};
        static_cast<void>(transport.publish(topic, message));
        static_cast<void>(transport.publish(topic, message));
        if (deliveries != 2)
            throw std::runtime_error("leased authorized transport did not delegate");

        std::atomic<Poco::UInt64> concurrentAudits{0};
        PolicyEngine concurrentEngine(allowedPolicy(), 128,
            [&](const AuditRecord&) { ++concurrentAudits; });
        DecisionLeaseOptions concurrentOptions;
        concurrentOptions.durationMilliseconds = 60000;
        concurrentOptions.maximumUses = 1000000;
        concurrentOptions.capacity = 16;
        DecisionLeaseAuthorizer concurrentLease(
            [&](const Request& request) { return concurrentEngine.decide(request); },
            [&] { return concurrentEngine.snapshot(); }, concurrentOptions);
        std::atomic<bool> concurrentFailure{false};
        std::vector<std::future<void>> workers;
        for (int worker = 0; worker < 8; ++worker)
            workers.push_back(std::async(std::launch::async, [&] {
                for (int iteration = 0; iteration < 1000; ++iteration)
                    if (!concurrentLease.authorize(first).allowed)
                        concurrentFailure = true;
            }));
        for (auto& worker : workers) worker.get();
        const auto concurrent = concurrentLease.snapshot();
        if (concurrentFailure || concurrent.hits < 7900 || concurrentAudits >= 100)
            throw std::runtime_error("concurrent lease path did not reduce authorization audits");

        std::cout << "DECISION_LEASE_SMOKE_OK hits=" << concurrent.hits
                  << " audits=" << concurrentAudits.load()
                  << " invalidated=" << revoked.invalidated << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "DECISION_LEASE_SMOKE_FAILED: " << exception.what() << '\n';
        return 1;
    }
}
