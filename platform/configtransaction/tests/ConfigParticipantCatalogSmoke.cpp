#include "PocoDDS/ConfigTransaction/ConfigurationParticipantCatalog.h"
#include "PocoDDS/ConfigTransaction/TransactionEngine.h"

#include <Poco/AutoPtr.h>
#include <Poco/Exception.h>

#include <algorithm>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace
{
using namespace PocoDDS::ConfigTransaction;

class MemoryStore final : public TransactionStore
{
public:
    void initialize() override {}
    std::optional<Snapshot> current() const override { return snapshot; }
    void seed(const Snapshot& value) override
    {
        if (!snapshot) snapshot = value;
    }
    void replaceBootstrap(const Snapshot& value) override { snapshot = value; }
    std::optional<TransactionRecord> findByRequestId(
        const std::string&) const override { return {}; }
    void save(const TransactionRecord&) override {}
    void commit(const TransactionRecord&, const Snapshot& value) override
    {
        snapshot = value;
    }
    std::vector<TransactionRecord> incomplete() const override { return {}; }
    std::vector<TransactionRecord> history(std::size_t) const override { return {}; }

    std::optional<Snapshot> snapshot;
};

class Participant final : public ConfigurationParticipantService
{
public:
    Participant(std::string id, std::vector<std::string> prefixes,
                std::vector<std::string> after)
        : _descriptor{std::move(id), std::move(prefixes), std::move(after)} {}

    ParticipantDescriptor descriptor() const override { return _descriptor; }
    ParticipantResult preflight(const Context&) override
    {
        return ParticipantResult::accepted();
    }
    ParticipantResult commit(const Context&) override
    {
        return ParticipantResult::accepted();
    }
    ParticipantResult rollback(const Context&) override
    {
        return ParticipantResult::accepted();
    }

private:
    ParticipantDescriptor _descriptor;
};
} // namespace

int main()
{
    using namespace PocoDDS::ConfigTransaction;
    TransactionEngine engine(std::make_unique<MemoryStore>());
    const auto empty = configurationParticipantCatalog(engine);
    if (empty.generation != 0 || !empty.participants.empty() ||
        empty.digest.size() != 64) return 1;
    engine.initialize({{"a.value", "1"}, {"b.value", "1"}});

    auto registrationB = engine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
        new Participant("b", {"b.value", "b.extra"}, {"a"})));
    const auto unresolved = configurationParticipantCatalog(engine);
    if (unresolved.generation != 1 || unresolved.participants.size() != 1 ||
        unresolved.participants[0].unresolvedAfter !=
            std::vector<std::string>({"a"})) return 2;
    auto registrationA = engine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
        new Participant("a", {"a"}, {})));
    const auto first = configurationParticipantCatalog(engine);
    if (first.generation != 2 || first.participants.size() != 2 ||
        first.participants[0].id != "a" ||
        first.participants[0].ownedPrefixes != std::vector<std::string>({"a"}) ||
        first.participants[0].registrationGeneration != 2 ||
        first.participants[1].id != "b" ||
        first.participants[1].ownedPrefixes !=
            std::vector<std::string>({"b.extra", "b.value"}) ||
        first.participants[1].after != std::vector<std::string>({"a"}) ||
        !first.participants[1].unresolvedAfter.empty() ||
        first.participants[1].registrationGeneration != 1) return 3;
    const auto repeated = configurationParticipantCatalog(engine);
    if (repeated.generation != first.generation ||
        repeated.digest != first.digest) return 4;

    bool overlapRejected = false;
    try
    {
        static_cast<void>(engine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
            new Participant("overlap", {"a.value"}, {}))));
    }
    catch (const Poco::ExistsException&)
    {
        overlapRejected = true;
    }
    const auto afterRejected = configurationParticipantCatalog(engine);
    if (!overlapRejected || afterRejected.generation != first.generation ||
        afterRejected.digest != first.digest) return 5;

    bool internalOverlapRejected = false;
    try
    {
        static_cast<void>(engine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
            new Participant("internal-overlap", {"internal", "internal.value"}, {}))));
    }
    catch (const Poco::InvalidArgumentException&)
    {
        internalOverlapRejected = true;
    }
    const auto afterInternalRejected = configurationParticipantCatalog(engine);
    if (!internalOverlapRejected ||
        afterInternalRejected.generation != first.generation ||
        afterInternalRejected.digest != first.digest) return 6;

    registrationB.reset();
    const auto detached = configurationParticipantCatalog(engine);
    if (detached.generation != 3 || detached.participants.size() != 1 ||
        detached.participants[0].id != "a" || detached.digest == first.digest) return 7;

    registrationB = engine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
        new Participant("b", {"b.extra", "b.value"}, {"a"})));
    const auto reattached = configurationParticipantCatalog(engine);
    if (reattached.generation != 4 || reattached.participants.size() != 2 ||
        reattached.participants[1].registrationGeneration != 4 ||
        reattached.digest == first.digest || reattached.digest == detached.digest) return 8;

    TransactionEngine cycleEngine(std::make_unique<MemoryStore>());
    cycleEngine.initialize({{"cycle-a.value", "1"}, {"cycle-b.value", "1"}});
    auto cycleB = cycleEngine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
        new Participant("cycle-b", {"cycle-b"}, {"cycle-a"})));
    bool cycleRejected = false;
    try
    {
        static_cast<void>(cycleEngine.attach(
            Poco::AutoPtr<ConfigurationParticipantService>(
                new Participant("cycle-a", {"cycle-a"}, {"cycle-b"}))));
    }
    catch (const Poco::InvalidArgumentException&)
    {
        cycleRejected = true;
    }
    const auto afterCycleRejected = configurationParticipantCatalog(cycleEngine);
    if (!cycleRejected || afterCycleRejected.generation != 1 ||
        afterCycleRejected.participants.size() != 1 ||
        afterCycleRejected.participants[0].unresolvedAfter !=
            std::vector<std::string>({"cycle-a"})) return 9;
    auto cycleA = cycleEngine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
        new Participant("cycle-a", {"cycle-a"}, {})));
    const auto resolvedCycleGraph = configurationParticipantCatalog(cycleEngine);
    if (resolvedCycleGraph.generation != 2 ||
        resolvedCycleGraph.participants.size() != 2 ||
        !resolvedCycleGraph.participants[1].unresolvedAfter.empty()) return 10;

    TransactionEngine isolated(std::make_unique<MemoryStore>());
    if (configurationParticipantCatalog(isolated).generation != 0 ||
        !configurationParticipantCatalog(isolated).participants.empty()) return 11;

    std::cout << "PDR_CONFIG_PARTICIPANT_CATALOG_PASS generation=1 digest=1 "
                 "sorted=1 detach=1 reregister=1 isolated=1 unresolved=1 "
                 "cycleRejected=1 internalOverlapRejected=1\n";
    return 0;
}
