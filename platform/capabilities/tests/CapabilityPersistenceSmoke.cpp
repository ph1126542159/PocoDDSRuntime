#include "PocoDDS/Capabilities/PolicyEngine.h"
#include "PocoDDS/Capabilities/SqlitePolicyStore.h"

#include <Poco/Data/SQLite/Connector.h>
#include <Poco/Data/Session.h>
#include <Poco/Data/Statement.h>
#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/TemporaryFile.h>
#include <Poco/UUIDGenerator.h>

#include <iostream>
#include <atomic>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using namespace PocoDDS::Capabilities;
using namespace Poco::Data::Keywords;

namespace
{
std::vector<Rule> seedPolicy()
{
    return {
        {"operator-admin", Effect::allow, "operator", ResourceKind::service,
         "pdr.service.capabilityRuntime", {Action::use}},
        {"sensor-read", Effect::allow, "sensor.one", ResourceKind::topic,
         "telemetry.one", {Action::subscribe}}};
}

void removeDatabase(const std::string& path)
{
    for (const auto& suffix : {std::string(), std::string("-wal"), std::string("-shm"),
                               std::string(".lock")})
    {
        Poco::File file(path + suffix);
        if (file.exists()) file.remove();
    }
}
} // namespace

int main()
{
    Poco::Path path(Poco::TemporaryFile::tempName());
    path.setFileName("pdr-capability-persistence-" +
        Poco::UUIDGenerator::defaultGenerator().createRandom().toString() + ".sqlite");
    const auto database = path.toString();
    const auto concurrentDatabase = database + ".concurrent";
    try
    {
        const auto seed = seedPolicy();
        std::vector<Rule> replacement = seed;
        replacement.push_back({"sensor-publish", Effect::allow, "sensor.one",
            ResourceKind::topic, "telemetry.one", {Action::publish}});
        {
            auto store = std::make_shared<SqlitePolicyStore>(database, 3);
            const auto initial = store->initialize(seed);
            if (initial.snapshot.generation != 1 || initial.snapshot.digest != policyDigest(seed))
                throw std::runtime_error("seed policy was not persisted at generation one");
            bool leaseRejected = false;
            try { SqlitePolicyStore competing(database, 3); }
            catch (const Poco::FileException&) { leaseRejected = true; }
            if (!leaseRejected)
                throw std::runtime_error("a second policy store bypassed the exclusive lease");
            PolicyEngine engine(initial.rules, initial.snapshot.generation, 32,
                [store](const AuditRecord& record) { store->appendAudit(record); });
            if (!engine.decide(
                    {"sensor.one", ResourceKind::topic, "telemetry.one", Action::subscribe})
                     .allowed)
                throw std::runtime_error("recovered seed policy did not authorize");
            if (engine.decide(
                    {"intruder", ResourceKind::topic, "telemetry.one", Action::subscribe})
                    .allowed)
                throw std::runtime_error("default deny was not persisted to audit");

            ReplaceRequest request{"replace-persistent", "operator", 1, replacement};
            const auto committed = store->replace(request);
            engine.restore(replacement, committed.snapshot.generation);
            const auto replay = store->replace(request);
            if (committed.snapshot.generation != 2 || replay.snapshot.generation != 2 ||
                !replay.idempotentReplay)
                throw std::runtime_error("persistent replacement idempotency failed");
            bool stale = false;
            try
            {
                static_cast<void>(store->replace(
                    {"stale-request", "operator", 1, replacement}));
            }
            catch (const Poco::InvalidArgumentException&) { stale = true; }
            if (!stale || !store->snapshot().healthy)
                throw std::runtime_error("generation conflict damaged persistence health");

            for (int index = 0; index < 5; ++index)
                static_cast<void>(engine.decide(
                    {"intruder." + std::to_string(index), ResourceKind::topic,
                     "telemetry.one", Action::subscribe}));
            if (store->audit(100).size() != 3 || store->snapshot().auditRecords != 3)
                throw std::runtime_error("durable audit retention was not enforced");
        }

        {
            SqlitePolicyStore recovered(database, 3);
            const auto state = recovered.initialize({});
            if (state.snapshot.generation != 2 ||
                state.snapshot.digest != policyDigest(replacement) ||
                state.rules.size() != replacement.size())
                throw std::runtime_error("persisted policy did not survive restart");
            PolicyEngine engine(state.rules, state.snapshot.generation, 16);
            if (!engine.decide(
                    {"sensor.one", ResourceKind::topic, "telemetry.one", Action::publish})
                     .allowed)
                throw std::runtime_error("recovered generation did not become active");

            Poco::Data::SQLite::Connector::registerConnector();
            Poco::Data::Session session("SQLite", database);
            const std::string corrupted = "temporary-invalid-digest";
            session << "UPDATE capability_policy_state SET digest=? WHERE singleton=1",
                useRef(corrupted), now;
            bool detected = false;
            try { static_cast<void>(recovered.current()); }
            catch (const Poco::DataFormatException&) { detected = true; }
            if (!detected || !recovered.snapshot().recoveryRequired)
                throw std::runtime_error("live policy corruption did not enter recovery state");
            const auto restoredDigest = policyDigest(replacement);
            session << "UPDATE capability_policy_state SET digest=? WHERE singleton=1",
                useRef(restoredDigest), now;
            bool stayedClosed = false;
            try { static_cast<void>(recovered.current()); }
            catch (const Poco::IllegalStateException&) { stayedClosed = true; }
            if (!stayedClosed)
                throw std::runtime_error("persistence resumed without explicit integrity verification");
            recovered.verifyIntegrity();
            if (recovered.snapshot().recoveryRequired ||
                recovered.current().snapshot.generation != 2)
                throw std::runtime_error("integrity verification did not clear recovery state");
        }

        Poco::Data::SQLite::Connector::registerConnector();
        {
            Poco::Data::Session session("SQLite", database);
            const std::string corrupted = "not-the-policy-digest";
            session << "UPDATE capability_policy_state SET digest=? WHERE singleton=1",
                useRef(corrupted), now;
        }
        bool corruptionRejected = false;
        try
        {
            SqlitePolicyStore corrupted(database, 3);
            static_cast<void>(corrupted.initialize(seed));
        }
        catch (const Poco::DataFormatException&) { corruptionRejected = true; }
        if (!corruptionRejected)
            throw std::runtime_error("silent policy corruption did not fail closed");

        {
            auto store = std::make_shared<SqlitePolicyStore>(concurrentDatabase, 16);
            static_cast<void>(store->initialize(seed));
            auto first = seed;
            first.push_back({"concurrent-publish", Effect::allow, "sensor.one",
                ResourceKind::topic, "telemetry.one", {Action::publish}});
            auto second = seed;
            second.push_back({"concurrent-subscribe", Effect::allow, "sensor.two",
                ResourceKind::topic, "telemetry.two", {Action::subscribe}});
            std::atomic<int> committed{0};
            std::atomic<int> conflicted{0};
            const auto replace = [&](const std::string& requestId,
                                     const std::vector<Rule>& rules)
            {
                try
                {
                    const auto result = store->replace(
                        {requestId, "operator", 1, rules});
                    if (result.snapshot.generation == 2) ++committed;
                }
                catch (const Poco::InvalidArgumentException&) { ++conflicted; }
            };
            std::thread left(replace, "concurrent-left", std::cref(first));
            std::thread right(replace, "concurrent-right", std::cref(second));
            left.join();
            right.join();
            if (committed != 1 || conflicted != 1 ||
                store->current().snapshot.generation != 2)
                throw std::runtime_error(
                    "concurrent policy replacements did not commit exactly one generation");
        }

        removeDatabase(database);
        removeDatabase(concurrentDatabase);
        std::cout << "CAPABILITY_PERSISTENCE_SMOKE_OK generation=2 retention=3 concurrent=1\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        removeDatabase(database);
        removeDatabase(concurrentDatabase);
        std::cerr << "CAPABILITY_PERSISTENCE_SMOKE_FAILED: " << exception.what() << '\n';
        return 1;
    }
}
