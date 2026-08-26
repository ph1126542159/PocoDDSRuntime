#include "SqliteInvocationJournal.h"

#include "PocoDDS/ServiceClient/RuntimeCoordinator.h"

#include <Poco/File.h>
#include <Poco/TemporaryFile.h>

#include <chrono>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace std::chrono_literals;
using namespace PocoDDS::ResourceGovernance;
using namespace PocoDDS::ServiceClient;
using namespace PocoDDS::ServiceDirectory;

namespace
{
void require(bool condition, const std::string& detail)
{
    if (!condition) throw std::runtime_error(detail);
}

InvocationCompletion completion()
{
    InvocationCompletion value;
    value.invocationId = "invocation-a";
    value.governance = {"test.service-client", "work-a",
                        CompletionStatus::succeeded, "",
                        11us, 23us};
    InvocationResult result;
    result.status = InvocationStatus::succeeded;
    result.attempts = 1;
    result.payload = {0x00, 0x4f, 0x4b, 0xff};
    result.code = "ok";
    result.detail = "completed";
    InstanceSnapshot instance;
    instance.advertisement.serviceName = "orders.v1";
    instance.advertisement.instanceId = "orders-a";
    instance.advertisement.endpoint = "loopback://orders-a";
    instance.advertisement.protocol = "loopback";
    instance.advertisement.zone = "test";
    instance.advertisement.tags = {"json", "primary"};
    instance.advertisement.state = AdvertisedState::ready;
    instance.advertisement.runtimeId = "runtime-a";
    instance.advertisement.runtimeIncarnation = 7;
    instance.advertisement.revision = 9;
    instance.state = InstanceState::ready;
    instance.age = 17ms;
    result.instance = instance;
    result.history.push_back({1, "orders-a", "runtime-a", 7,
                              AttemptDisposition::succeeded, "ok"});
    value.invocation = std::move(result);
    return value;
}

void removeDatabase(const std::string& path)
{
    for (const auto& suffix : {std::string{}, std::string("-wal"),
                               std::string("-shm")})
    {
        Poco::File file(path + suffix);
        if (file.exists()) file.remove();
    }
}
} // namespace

int main()
{
    const auto database = Poco::TemporaryFile::tempName() + ".sqlite";
    try
    {
        const std::string scopeA(64, 'a');
        const std::string scopeB(64, 'b');
        const std::string scopeC(64, 'c');
        const std::string requestA(64, '1');
        const std::string requestB(64, '2');
        {
            SqliteInvocationJournal journal(database, 2, 1000ms);
            const auto acquired = journal.claim(
                {scopeA, requestA, "invocation-a", 1000000});
            require(acquired.status == InvocationJournalClaimStatus::acquired,
                    "first idempotency claim was not acquired");
            const auto inFlight = journal.claim(
                {scopeA, requestA, "invocation-duplicate", 1050000});
            require(inFlight.status ==
                        InvocationJournalClaimStatus::indeterminate &&
                    inFlight.invocationId == "invocation-a",
                    "in-flight claim was not fail-closed");
            const auto conflict = journal.claim(
                {scopeA, requestB, "invocation-conflict", 1050000});
            require(conflict.status == InvocationJournalClaimStatus::conflict,
                    "same key with a different request did not conflict");
            journal.complete(scopeA, requestA, "invocation-a",
                             completion(), 1100000);
            const auto state = journal.snapshot();
            require(state.enabled && state.durable && state.healthy &&
                        state.backend == "sqlite-wal-full" &&
                        state.entries == 1 && state.inFlight == 0 &&
                        state.completed == 1,
                    "completed journal snapshot is incorrect");
        }

        {
            SqliteInvocationJournal journal(database, 2, 1000ms);
            const auto replay = journal.claim(
                {scopeA, requestA, "invocation-replay", 1200000});
            require(replay.status ==
                        InvocationJournalClaimStatus::replayCompleted &&
                        replay.invocationId == "invocation-a" &&
                        replay.completion && replay.completion->invocation &&
                        replay.completion->invocation->payload ==
                            std::vector<std::uint8_t>(
                                {0x00, 0x4f, 0x4b, 0xff}) &&
                        replay.completion->invocation->instance &&
                        replay.completion->invocation->instance->advertisement
                                .runtimeIncarnation == 7 &&
                        replay.completion->invocation->history.size() == 1,
                    "completed invocation did not survive SQLite reopen");
            require(!journal.release(scopeA, requestA, "invocation-a"),
                    "completed journal entry was released");

            const auto afterTtl = journal.claim(
                {scopeA, requestA, "invocation-after-ttl", 2200001});
            require(afterTtl.status == InvocationJournalClaimStatus::acquired,
                    "expired completion was not reclaimed");
            require(static_cast<bool>(journal.claim(
                        {scopeB, requestA, "invocation-b", 2200001})),
                    "second in-flight claim was not acquired");
            const auto full = journal.claim(
                {scopeC, requestA, "invocation-c", 2200001});
            require(full.status ==
                        InvocationJournalClaimStatus::capacityExceeded,
                    "all-in-flight journal capacity did not fail closed");
            require(journal.release(scopeB, requestA, "invocation-b"),
                    "matching in-flight claim was not released");
            require(static_cast<bool>(journal.claim(
                        {scopeC, requestA, "invocation-c", 2200001})),
                    "released capacity was not reusable");
        }

        removeDatabase(database);
        std::cout << "SERVICE_CLIENT_INVOCATION_JOURNAL_PASS backend=sqlite-wal-full\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        removeDatabase(database);
        std::cerr << "SERVICE_CLIENT_INVOCATION_JOURNAL_ERROR: "
                  << exception.what() << '\n';
        return 1;
    }
}
