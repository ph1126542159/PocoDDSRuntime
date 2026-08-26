#include "PocoDDS/Capabilities/AuthorizedTransport.h"
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
Rule rule(std::string id, Effect effect, std::string principal, ResourceKind kind,
          std::string resource, std::vector<Action> actions)
{
    return {std::move(id), effect, std::move(principal), kind, std::move(resource),
            std::move(actions)};
}
} // namespace

int main()
{
    try
    {
        std::vector<Rule> rules{
            rule("allow-telemetry", Effect::allow, "bundle.sensor.*", ResourceKind::topic,
                 "telemetry.*", {Action::publish, Action::subscribe}),
            rule("deny-secret", Effect::deny, "bundle.sensor.bad", ResourceKind::topic,
                 "telemetry.secret", {Action::publish}),
            rule("allow-config", Effect::allow, "bundle.admin", ResourceKind::configuration,
                 "logging.*", {Action::write})};
        PolicyEngine engine(rules, 4096);

        const auto allowed = engine.decide(
            {"bundle.sensor.one", ResourceKind::topic, "telemetry.temperature", Action::publish});
        if (!allowed.allowed || allowed.matchedRuleId != "allow-telemetry")
            throw std::runtime_error("prefix allow rule did not match");
        const auto denied = engine.decide(
            {"bundle.sensor.bad", ResourceKind::topic, "telemetry.secret", Action::publish});
        if (denied.allowed || denied.code != "CAPABILITY_EXPLICIT_DENY")
            throw std::runtime_error("explicit deny did not override allow");
        const auto implicit = engine.decide(
            {"bundle.unknown", ResourceKind::topic, "telemetry.temperature", Action::subscribe});
        if (implicit.allowed || implicit.code != "CAPABILITY_DEFAULT_DENY")
            throw std::runtime_error("default deny was not applied");

        bool invalidAction = false;
        try
        {
            validateRule(rule("invalid-action", Effect::allow, "bundle.x", ResourceKind::device,
                              "device.x", {Action::publish}));
        }
        catch (const Poco::InvalidArgumentException&) { invalidAction = true; }
        if (!invalidAction) throw std::runtime_error("invalid resource/action pair accepted");

        bool unknownPolicyField = false;
        try
        {
            static_cast<void>(parsePolicyDocument(
                R"({"version":1,"defaultEffect":"deny","rules":[],"actor":"spoofed"})"));
        }
        catch (const Poco::InvalidArgumentException&) { unknownPolicyField = true; }
        if (!unknownPolicyField)
            throw std::runtime_error("unknown policy field bypassed strict parsing");
        bool missingDefault = false;
        try { static_cast<void>(parsePolicyDocument(R"({"version":1,"rules":[]})")); }
        catch (const Poco::InvalidArgumentException&) { missingDefault = true; }
        if (!missingDefault)
            throw std::runtime_error("policy without explicit default deny was accepted");

        const auto before = engine.snapshot();
        auto replacement = rules;
        replacement.push_back(rule("allow-commands", Effect::allow, "bundle.sensor.one",
            ResourceKind::topic, "commands.one", {Action::subscribe}));
        const auto replaced = engine.replace(
            {"replace-1", "operator", before.generation, replacement});
        const auto replay = engine.replace(
            {"replace-1", "operator", before.generation, replacement});
        if (replaced.snapshot.generation != before.generation + 1 || !replay.idempotentReplay)
            throw std::runtime_error("policy replacement idempotency failed");

        std::atomic<bool> failed{false};
        std::vector<std::future<void>> readers;
        for (int thread = 0; thread < 8; ++thread)
            readers.push_back(std::async(std::launch::async, [&] {
                for (int iteration = 0; iteration < 1000; ++iteration)
                {
                    const auto decision = engine.decide({"bundle.sensor.one", ResourceKind::topic,
                        "telemetry.temperature", Action::publish});
                    if (!decision.allowed || decision.policyDigest.empty()) failed = true;
                }
            }));
        auto second = replacement;
        second.push_back(rule("allow-device", Effect::allow, "bundle.sensor.one",
            ResourceKind::device, "sensor.one", {Action::observe}));
        static_cast<void>(engine.replace(
            {"replace-2", "operator", replaced.snapshot.generation, second}));
        for (auto& reader : readers) reader.get();
        if (failed) throw std::runtime_error("concurrent decision observed invalid snapshot");

        auto delegate = std::make_shared<InProcessTransport>();
        AuthorizedTransport sensor("bundle.sensor.one", delegate,
            [&](const Request& request) { return engine.decide(request); });
        TopicSpec topic{"telemetry.temperature", "sample", "1", Delivery::bestEffort, false};
        std::size_t deliveries = 0;
        auto subscription = sensor.subscribe(topic,
            [&](const TopicSpec&, const Message&) { ++deliveries; });
        Message message{"sample", "1", std::make_shared<const Payload>(Payload{1}), {}, {}};
        const auto published = sensor.publish(topic, message);
        if (published.delivered != 1 || deliveries != 1)
            throw std::runtime_error("authorized transport did not delegate");

        AuthorizedTransport unknown("bundle.unknown", delegate,
            [&](const Request& request) { return engine.decide(request); });
        bool transportDenied = false;
        try { static_cast<void>(unknown.publish(topic, message)); }
        catch (const Poco::NoPermissionException&) { transportDenied = true; }
        if (!transportDenied) throw std::runtime_error("transport guard did not deny publish");
        if (engine.audit(1000).size() < 10)
            throw std::runtime_error("authorization audit trail is incomplete");

        PolicyEngine unavailableAudit(rules, 16, [](const AuditRecord&) {
            throw Poco::IOException("durable audit unavailable");
        });
        bool auditFailedClosed = false;
        try
        {
            static_cast<void>(unavailableAudit.decide(
                {"bundle.sensor.one", ResourceKind::topic,
                 "telemetry.temperature", Action::publish}));
        }
        catch (const Poco::IOException&) { auditFailedClosed = true; }
        if (!auditFailedClosed)
            throw std::runtime_error("audit failure did not block authorization");

        std::cout << "CAPABILITIES_SMOKE_OK generation=" << engine.snapshot().generation
                  << " audit=" << engine.audit(1000).size() << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "CAPABILITIES_SMOKE_FAILED: " << exception.what() << '\n';
        return 1;
    }
}
