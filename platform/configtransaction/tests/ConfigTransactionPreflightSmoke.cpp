#include "PocoDDS/ConfigTransaction/ConfigurationPreflight.h"
#include "PocoDDS/ConfigTransaction/TransactionEngine.h"

#include <Poco/AutoPtr.h>
#include <Poco/Exception.h>

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <future>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace
{
using namespace PocoDDS::ConfigTransaction;

class CountingStore final : public TransactionStore
{
public:
    void initialize() override { initialized = true; }
    std::optional<Snapshot> current() const override { return snapshot; }
    void seed(const Snapshot& value) override
    {
        if (!snapshot) snapshot = value;
    }
    void replaceBootstrap(const Snapshot& value) override { snapshot = value; }
    std::optional<TransactionRecord> findByRequestId(
        const std::string& requestId) const override
    {
        const auto found = std::find_if(records.begin(), records.end(),
            [&](const auto& record) { return record.requestId == requestId; });
        return found == records.end()
            ? std::optional<TransactionRecord>{} : std::optional<TransactionRecord>{*found};
    }
    void save(const TransactionRecord& record) override
    {
        ++saveCalls;
        replaceRecord(record);
    }
    void commit(const TransactionRecord& record, const Snapshot& value) override
    {
        ++commitCalls;
        snapshot = value;
        replaceRecord(record);
    }
    std::vector<TransactionRecord> incomplete() const override { return {}; }
    std::vector<TransactionRecord> history(std::size_t limit) const override
    {
        const auto count = std::min(limit, records.size());
        return {records.begin(), records.begin() + static_cast<std::ptrdiff_t>(count)};
    }

    bool initialized{false};
    std::size_t saveCalls{0};
    std::size_t commitCalls{0};
    std::optional<Snapshot> snapshot;
    std::vector<TransactionRecord> records;

private:
    void replaceRecord(const TransactionRecord& record)
    {
        const auto found = std::find_if(records.begin(), records.end(),
            [&](const auto& current) { return current.id == record.id; });
        if (found == records.end()) records.push_back(record);
        else *found = record;
    }
};

struct ParticipantState
{
    std::mutex mutex;
    std::vector<std::string> events;
    bool rejectB{false};
    std::size_t commits{0};
    std::size_t rollbacks{0};
};

class Participant final : public ConfigurationParticipantService
{
public:
    Participant(std::string id, std::vector<std::string> prefixes,
                std::vector<std::string> after,
                std::shared_ptr<ParticipantState> state)
        : _descriptor{std::move(id), std::move(prefixes), std::move(after)},
          _state(std::move(state)) {}

    ParticipantDescriptor descriptor() const override { return _descriptor; }

    ParticipantResult preflight(const Context&) override
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        _state->events.push_back("preflight:" + _descriptor.id);
        if (_descriptor.id == "b" && _state->rejectB)
            return ParticipantResult::rejected(
                "preflight-test", "participant b rejected preview");
        return ParticipantResult::accepted();
    }

    ParticipantResult commit(const Context&) override
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        _state->events.push_back("commit:" + _descriptor.id);
        ++_state->commits;
        return ParticipantResult::accepted();
    }

    ParticipantResult rollback(const Context&) override
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        _state->events.push_back("rollback:" + _descriptor.id);
        ++_state->rollbacks;
        return ParticipantResult::accepted();
    }

private:
    ParticipantDescriptor _descriptor;
    std::shared_ptr<ParticipantState> _state;
};

struct BlockingState
{
    std::mutex mutex;
    std::condition_variable changed;
    bool entered{false};
    bool released{false};
};

class BlockingParticipant final : public ConfigurationParticipantService
{
public:
    explicit BlockingParticipant(std::shared_ptr<BlockingState> state)
        : _state(std::move(state)) {}

    ParticipantDescriptor descriptor() const override
    {
        return {"blocking", {"blocking"}, {}};
    }

    ParticipantResult preflight(const Context&) override
    {
        std::unique_lock<std::mutex> lock(_state->mutex);
        _state->entered = true;
        _state->changed.notify_all();
        _state->changed.wait(lock, [&] { return _state->released; });
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
    std::shared_ptr<BlockingState> _state;
};
} // namespace

int main()
{
    using namespace PocoDDS::ConfigTransaction;
    const Values initial{{"a.value", "1"}, {"b.value", "1"}};
    const Values candidate{{"a.value", "2"}, {"b.value", "2"}};
    auto storeOwner = std::make_unique<CountingStore>();
    auto* store = storeOwner.get();
    auto state = std::make_shared<ParticipantState>();
    std::size_t validations = 0;
    std::size_t activations = 0;
    std::size_t authorizations = 0;

    TransactionEngine engine(std::move(storeOwner),
        {[&](const Snapshot&) { ++validations; },
         [&](const Snapshot&) { ++activations; },
         [&](const std::string&, const std::vector<std::string>&) {
             ++authorizations;
         }});
    engine.initialize(initial);
    auto registrationA = engine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
        new Participant("a", {"a"}, {}, state)));
    auto registrationB = engine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
        new Participant("b", {"b"}, {"a"}, state)));

    const auto accepted = preflightConfigurationTransaction(engine,
        {"preview-accepted", 1, candidate, "operator"});
    if (!accepted.accepted || !accepted.changed || accepted.preflightId.empty() ||
        accepted.expectedGeneration != 1 || accepted.observedGeneration != 1 ||
        accepted.candidateGeneration != 2 ||
        accepted.candidateDigest != snapshotDigest(candidate) ||
        accepted.changedKeys != std::vector<std::string>({"a.value", "b.value"}) ||
        accepted.participants != std::vector<std::string>({"a", "b"}) ||
        !accepted.errorCode.empty()) return 1;
    if (store->saveCalls != 0 || store->commitCalls != 0 ||
        !store->records.empty() || engine.current().generation != 1 ||
        activations != 1) return 2;
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        if (state->events != std::vector<std::string>(
                {"preflight:a", "preflight:b"}) ||
            state->commits != 0 || state->rollbacks != 0) return 3;
    }

    const auto validationCount = validations;
    const auto authorizationCount = authorizations;
    const auto stale = preflightConfigurationTransaction(engine,
        {"preview-stale", 2, candidate, "operator"});
    if (stale.accepted || stale.errorCode != "generation-conflict" ||
        stale.observedGeneration != 1 || stale.expectedGeneration != 2 ||
        validations != validationCount || authorizations != authorizationCount ||
        store->saveCalls != 0 || store->commitCalls != 0) return 4;

    const auto noChange = preflightConfigurationTransaction(engine,
        {"preview-no-change", 1, initial, "operator"});
    if (!noChange.accepted || noChange.changed || noChange.candidateGeneration != 1 ||
        noChange.candidateDigest != snapshotDigest(initial) ||
        !noChange.changedKeys.empty() || !noChange.participants.empty() ||
        store->saveCalls != 0 || store->commitCalls != 0) return 5;

    {
        std::lock_guard<std::mutex> lock(state->mutex);
        state->rejectB = true;
    }
    Values rejectedCandidate = candidate;
    rejectedCandidate["a.value"] = "3";
    const auto rejected = preflightConfigurationTransaction(engine,
        {"preview-rejected", 1, rejectedCandidate, "operator"});
    if (rejected.accepted || rejected.errorCode != "preflight-test" ||
        rejected.participants != std::vector<std::string>({"a", "b"}) ||
        engine.current().generation != 1 || store->saveCalls != 0 ||
        store->commitCalls != 0 || activations != 1) return 6;
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        state->rejectB = false;
    }

    const auto secondAccepted = preflightConfigurationTransaction(engine,
        {"preview-before-commit", 1, candidate, "operator"});
    if (!secondAccepted.accepted) return 7;
    std::size_t eventsBeforeApply = 0;
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        eventsBeforeApply = state->events.size();
    }
    const auto applied = engine.apply(
        {"commit-after-preview", 1, candidate, "operator"});
    if (applied.status != Status::committed || applied.snapshot.generation != 2 ||
        store->saveCalls == 0 || store->commitCalls != 1 || activations != 2 ||
        engine.current().generation != 2) return 8;
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        const std::vector<std::string> applyEvents(
            state->events.begin() + static_cast<std::ptrdiff_t>(eventsBeforeApply),
            state->events.end());
        if (applyEvents != std::vector<std::string>(
                {"preflight:a", "preflight:b", "commit:a", "commit:b"}) ||
            state->commits != 2 || state->rollbacks != 0) return 9;
    }

    Values topologyCandidate = candidate;
    topologyCandidate["b.value"] = "3";
    const auto topologyPlan = preflightConfigurationTransaction(engine,
        {"preview-topology", 2, topologyCandidate, "operator"});
    if (!topologyPlan.accepted) return 10;
    registrationB.reset();
    bool topologyRechecked = false;
    try
    {
        static_cast<void>(engine.apply(
            {"commit-topology-drift", 2, topologyCandidate, "operator"}));
    }
    catch (const Poco::InvalidArgumentException&)
    {
        topologyRechecked = true;
    }
    if (!topologyRechecked || engine.current().generation != 2 ||
        store->commitCalls != 1) return 11;

    auto blockingStore = std::make_unique<CountingStore>();
    auto blockingEngine = std::make_unique<TransactionEngine>(std::move(blockingStore));
    blockingEngine->initialize({{"blocking.value", "1"}});
    auto blockingState = std::make_shared<BlockingState>();
    auto blockingRegistration = blockingEngine->attach(
        Poco::AutoPtr<ConfigurationParticipantService>(
            new BlockingParticipant(blockingState)));
    auto* blockingRaw = blockingEngine.get();
    auto inFlight = std::async(std::launch::async, [blockingRaw] {
        return preflightConfigurationTransaction(*blockingRaw,
            {"preview-during-destruction", 1, {{"blocking.value", "2"}}, "operator"});
    });
    {
        std::unique_lock<std::mutex> lock(blockingState->mutex);
        if (!blockingState->changed.wait_for(
                lock, std::chrono::seconds(2),
                [&] { return blockingState->entered; })) return 12;
    }
    auto destruction = std::async(std::launch::async, [&] {
        blockingEngine.reset();
    });
    if (destruction.wait_for(std::chrono::milliseconds(100)) !=
        std::future_status::timeout) return 13;
    {
        std::lock_guard<std::mutex> lock(blockingState->mutex);
        blockingState->released = true;
        blockingState->changed.notify_all();
    }
    if (!inFlight.get().accepted) return 14;
    destruction.get();

    std::cout << "PDR_CONFIG_TRANSACTION_PREFLIGHT_PASS sideEffectFree=1 "
                 "generationConflict=1 participantOrder=1 commitRepreflight=1 "
                 "topologyRechecked=1 lifetimeBarrier=1\n";
    return 0;
}
