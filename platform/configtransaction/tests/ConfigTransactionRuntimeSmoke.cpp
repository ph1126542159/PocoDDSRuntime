#include "PocoDDS/ConfigTransaction/SqliteTransactionStore.h"
#include "PocoDDS/ConfigTransaction/TransactionEngine.h"

#include <Poco/AutoPtr.h>
#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/TemporaryFile.h>
#include <Poco/UUIDGenerator.h>

#include <algorithm>
#include <future>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

namespace
{
using namespace PocoDDS::ConfigTransaction;

struct ParticipantState
{
    std::mutex mutex;
    std::vector<std::string> events;
    bool rejectPreflight{false};
    bool rejectCommit{false};
    unsigned commits{0};
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
        append("preflight:" + _descriptor.id);
        return _state->rejectPreflight
            ? ParticipantResult::rejected("preflight-test", "rejected by test")
            : ParticipantResult::accepted();
    }

    ParticipantResult commit(const Context&) override
    {
        append("commit:" + _descriptor.id);
        {
            std::lock_guard<std::mutex> lock(_state->mutex);
            ++_state->commits;
        }
        return _state->rejectCommit
            ? ParticipantResult::rejected("commit-test", "rejected by test")
            : ParticipantResult::accepted();
    }

    ParticipantResult rollback(const Context&) override
    {
        append("rollback:" + _descriptor.id);
        return ParticipantResult::accepted();
    }

private:
    void append(std::string event)
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        _state->events.push_back(std::move(event));
    }

    ParticipantDescriptor _descriptor;
    std::shared_ptr<ParticipantState> _state;
};

std::vector<std::string> events(const std::shared_ptr<ParticipantState>& left,
                                const std::shared_ptr<ParticipantState>& right)
{
    std::vector<std::string> result;
    {
        std::lock_guard<std::mutex> lock(left->mutex);
        result.insert(result.end(), left->events.begin(), left->events.end());
    }
    {
        std::lock_guard<std::mutex> lock(right->mutex);
        result.insert(result.end(), right->events.begin(), right->events.end());
    }
    return result;
}
} // namespace

int main()
{
    using namespace PocoDDS::ConfigTransaction;
    Poco::Path path(Poco::TemporaryFile::tempName());
    path.setFileName("pdr-config-transaction-" +
                     Poco::UUIDGenerator::defaultGenerator().createRandom().toString() + ".sqlite");
    const std::string database = path.toString();
    Values active;
    std::mutex activeMutex;
    const Values initial{{"a.value", "1"}, {"b.value", "1"},
                         {"secret.password", "env://OLD_SECRET"}};
    if (!sensitiveValueAllowed("pdr.auth.tokenEnvironment", "PDR_AUTH_TOKEN") ||
        sensitiveValueAllowed("pdr.auth.token", "literal-secret")) return 18;

    auto stateA = std::make_shared<ParticipantState>();
    auto stateB = std::make_shared<ParticipantState>();
    auto stateSecret = std::make_shared<ParticipantState>();
    {
        TransactionEngine engine(
            std::make_unique<SqliteTransactionStore>(database),
            {{}, [&](const Snapshot& snapshot) {
                std::lock_guard<std::mutex> lock(activeMutex);
                active = snapshot.values;
            }});
        engine.initialize(initial);
        auto registrationA = engine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
            new Participant("a", {"a"}, {}, stateA)));
        auto registrationB = engine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
            new Participant("b", {"b"}, {"a"}, stateB)));
        auto registrationSecret = engine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
            new Participant("secret", {"secret"}, {}, stateSecret)));

        auto committed = engine.apply({"request-1", 1,
            {{"a.value", "2"}, {"b.value", "2"},
             {"secret.password", "env://OLD_SECRET"}}});
        if (committed.status != Status::committed || committed.snapshot.generation != 2 ||
            committed.participants != std::vector<std::string>({"a", "b"})) return 1;
        const auto replay = engine.apply({"request-1", 1,
            {{"a.value", "2"}, {"b.value", "2"},
             {"secret.password", "env://OLD_SECRET"}}});
        if (!replay.idempotentReplay || replay.transactionId != committed.transactionId) return 2;

        bool conflict = false;
        try { static_cast<void>(engine.apply({"stale", 1, initial})); }
        catch (const Poco::InvalidArgumentException&) { conflict = true; }
        if (!conflict) return 3;

        stateB->rejectCommit = true;
        auto rolledBack = engine.apply({"request-2", 2,
            {{"a.value", "3"}, {"b.value", "3"},
             {"secret.password", "env://OLD_SECRET"}}});
        if (rolledBack.status != Status::rolledBack || !rolledBack.rolledBack ||
            engine.current().generation != 2) return 4;
        {
            std::lock_guard<std::mutex> lock(activeMutex);
            if (active.at("a.value") != "2" || active.at("b.value") != "2") return 5;
        }
        stateB->rejectCommit = false;

        stateB->rejectPreflight = true;
        auto preflight = engine.apply({"request-3", 2,
            {{"a.value", "4"}, {"b.value", "4"},
             {"secret.password", "env://OLD_SECRET"}}});
        if (preflight.status != Status::preflightFailed || preflight.rolledBack) return 6;
        stateB->rejectPreflight = false;

        bool secretRejected = false;
        try { static_cast<void>(engine.apply({"secret-inline", 2,
            {{"a.value", "2"}, {"b.value", "2"},
             {"secret.password", "literal-secret"}}})); }
        catch (const Poco::InvalidArgumentException&) { secretRejected = true; }
        if (!secretRejected) return 7;

        bool overlapRejected = false;
        try
        {
            static_cast<void>(engine.attach(Poco::AutoPtr<ConfigurationParticipantService>(
                new Participant("overlap", {"a.value"}, {},
                                std::make_shared<ParticipantState>()))));
        }
        catch (const Poco::ExistsException&) { overlapRejected = true; }
        if (!overlapRejected) return 8;

        const Values concurrentCandidate{{"a.value", "5"}, {"b.value", "2"},
                                         {"secret.password", "env://OLD_SECRET"}};
        std::vector<std::future<ApplyResult>> concurrent;
        for (int index = 0; index < 8; ++index)
            concurrent.push_back(std::async(std::launch::async, [&engine, concurrentCandidate] {
                return engine.apply({"concurrent-request", 2, concurrentCandidate});
            }));
        std::string concurrentTransaction;
        unsigned replays = 0;
        for (auto& future : concurrent)
        {
            const auto result = future.get();
            if (result.status != Status::committed || result.snapshot.generation != 3) return 9;
            if (concurrentTransaction.empty()) concurrentTransaction = result.transactionId;
            if (result.transactionId != concurrentTransaction) return 10;
            if (result.idempotentReplay) ++replays;
        }
        if (replays != 7) return 11;
    }

    Snapshot current;
    {
        SqliteTransactionStore store(database);
        store.initialize();
        const auto loaded = store.current();
        if (!loaded || loaded->generation != 3) return 12;
        current = *loaded;
        TransactionRecord interrupted;
        interrupted.id = "interrupted-transaction";
        interrupted.requestId = "interrupted-request";
        interrupted.status = Status::committing;
        interrupted.previous = current;
        interrupted.candidate = current;
        interrupted.candidate.generation = current.generation + 1;
        interrupted.candidate.values["a.value"] = "6";
        interrupted.candidate.digest = snapshotDigest(interrupted.candidate.values);
        interrupted.changedKeys = {"a.value", "b.value"};
        interrupted.participants = {"a", "b"};
        interrupted.commitAttempted = {"a", "b"};
        interrupted.committedParticipants = {"a"};
        interrupted.createdMicroseconds = 1;
        interrupted.updatedMicroseconds = 2;
        store.save(interrupted);
    }

    auto recoveryA = std::make_shared<ParticipantState>();
    auto recoveryB = std::make_shared<ParticipantState>();
    {
        TransactionEngine recovered(std::make_unique<SqliteTransactionStore>(database));
        recovered.initialize(initial);
        if (recovered.recover() != 0) return 13;
        auto registrationA = recovered.attach(Poco::AutoPtr<ConfigurationParticipantService>(
            new Participant("a", {"a"}, {}, recoveryA)));
        if (recovered.recover() != 0) return 14;
        auto registrationB = recovered.attach(Poco::AutoPtr<ConfigurationParticipantService>(
            new Participant("b", {"b"}, {"a"}, recoveryB)));
        if (recovered.recover() != 1) return 15;
        const auto history = recovered.history();
        const auto interrupted = std::find_if(history.begin(), history.end(), [](const auto& item) {
            return item.id == "interrupted-transaction";
        });
        if (interrupted == history.end() || interrupted->status != Status::rolledBack) return 16;
    }

    {
        std::lock_guard<std::mutex> lockA(recoveryA->mutex);
        std::lock_guard<std::mutex> lockB(recoveryB->mutex);
        if (recoveryB->events != std::vector<std::string>({"rollback:b"}) ||
            recoveryA->events != std::vector<std::string>({"rollback:a"})) return 17;
    }

    try { Poco::File(database).remove(); } catch (...) {}
    try { Poco::File(database + "-wal").remove(); } catch (...) {}
    try { Poco::File(database + "-shm").remove(); } catch (...) {}
    std::cout << "PDR_CONFIG_TRANSACTION_RUNTIME_PASS two_phase=true rollback=true "
                 "recovery=true idempotency=true concurrency=8 secrets=references-only\n";
    return 0;
}
