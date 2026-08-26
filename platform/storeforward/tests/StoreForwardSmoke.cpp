#include "PocoDDS/StoreForward/OutboxEngine.h"
#include "PocoDDS/StoreForward/SqliteOutboxStore.h"

#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/UUIDGenerator.h>

#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace
{
using namespace PocoDDS::StoreForward;

void require(bool condition, const std::string& message)
{
    if (!condition) throw std::runtime_error(message);
}

std::string temporaryDatabase()
{
    Poco::Path path(Poco::Path::temp());
    path.append("pdr-outbox-" +
                Poco::UUIDGenerator::defaultGenerator().createRandom().toString() + ".sqlite");
    return path.toString();
}

void removeDatabase(const std::string& path)
{
    for (const auto& suffix : {std::string{}, std::string{"-wal"}, std::string{"-shm"}})
    {
        Poco::File file(path + suffix);
        if (file.exists()) file.remove();
    }
}

class RecordingProvider final : public DeliveryProviderService
{
public:
    explicit RecordingProvider(std::string type = "recording")
        : _type(std::move(type))
    {
    }

    ProviderDescriptor descriptor() const override
    {
        return {_type, "1.0.0", 1024};
    }

    DeliveryResult deliver(const DeliveryRequest& request) override
    {
        calls.push_back(request.idempotencyKey + ":" + std::to_string(request.attempt));
        if (request.payload == "retry-once" && request.attempt == 1)
            return DeliveryResult::retryAfter(
                std::chrono::milliseconds(0), "offline", "link unavailable");
        if (request.payload == "permanent" && !allowPermanent)
            return DeliveryResult::permanent("rejected", "destination rejected payload");
        return DeliveryResult::ack();
    }

    bool allowPermanent{false};
    std::vector<std::string> calls;

private:
    std::string _type;
};

Policy immediatePolicy()
{
    Policy policy;
    policy.maximumActiveMessages = 16;
    policy.maximumPayloadBytes = 1024;
    policy.maximumAttempts = 3;
    policy.initialRetryDelay = std::chrono::milliseconds(0);
    policy.maximumRetryDelay = std::chrono::milliseconds(0);
    policy.deliveryBatchSize = 16;
    policy.terminalRetention = std::chrono::hours(0);
    return policy;
}
} // namespace

int main()
{
    const std::string path = temporaryDatabase();
    const std::string recoveryPath = temporaryDatabase();
    const std::string quotaPath = temporaryDatabase();
    try
    {
        {
        Poco::AutoPtr<RecordingProvider> provider = new RecordingProvider;
        Poco::Int64 fakeNow = 1'000'000;
        OutboxEngine engine(std::make_unique<SqliteOutboxStore>(path), immediatePolicy(),
                            [&fakeNow] { return fakeNow++; });
        engine.initialize();
        engine.attach(provider);

        const auto first = engine.enqueue(
            {"recording", "topic/one", "first", "device-42", "retry-once", 0});
        const auto second = engine.enqueue(
            {"recording", "topic/two", "second", "device-42", "ok", 0});
        const auto duplicate = engine.enqueue(
            {"recording", "changed", "first", "different-order", "different", 0});
        require(duplicate.id == first.id, "idempotent enqueue created a duplicate");

        require(engine.pump() == 1, "first ordered delivery was not attempted");
        require(engine.get(first.id).state == State::pending,
                "retryable delivery was not returned to pending");
        require(engine.get(second.id).state == State::pending,
                "later ordered message bypassed its predecessor");
        require(engine.pump() == 1 && engine.get(first.id).state == State::delivered,
                "first ordered message was not acknowledged on retry");
        require(engine.get(second.id).state == State::pending,
                "second ordered message was delivered in the same checkpoint batch");
        require(engine.pump() == 1 && engine.get(second.id).state == State::delivered,
                "second ordered message did not advance after predecessor acknowledgement");
        require(provider->calls == std::vector<std::string>{
                    "first:1", "first:2", "second:1"},
                "provider call order or attempt accounting is incorrect");

        auto dead = engine.enqueue(
            {"recording", "topic/dead", "dead", "", "permanent", 0});
        require(engine.pump() == 1, "permanent failure was not processed");
        dead = engine.get(dead.id);
        require(dead.state == State::deadLetter && dead.lastErrorCode == "rejected",
                "permanent failure did not enter the dead-letter state");
        provider->allowPermanent = true;
        require(engine.redrive(dead.id).state == State::pending,
                "dead-letter message was not redriven");
        require(engine.pump() == 1 && engine.get(dead.id).state == State::delivered,
                "redriven message was not delivered");

        const auto offline = engine.enqueue(
            {"late-provider", "topic/offline", "offline", "", "ok", 0});
        require(engine.pump() == 0 && engine.get(offline.id).state == State::pending,
                "message without a provider was not retained");
        Poco::AutoPtr<RecordingProvider> lateProvider =
            new RecordingProvider("late-provider");
        engine.attach(lateProvider);
        require(engine.pump() == 1 && engine.get(offline.id).state == State::delivered,
                "retained message was not delivered after provider attachment");

        const auto expiring = engine.enqueue(
            {"recording", "topic/expiry", "expiry", "",
             "ok", fakeNow + 1000});
        fakeNow += 2000;
        require(engine.pump() == 1 && engine.get(expiring.id).state == State::deadLetter,
                "expired message was delivered instead of dead-lettered");
        const auto snapshot = engine.snapshot();
        require(snapshot.delivered == 4 && snapshot.deadLetter == 1,
                "outbox snapshot counters are incorrect");
        require(engine.purge() == 4, "terminal retention purge count is incorrect");
        require(engine.list().size() == 1,
                "purge removed dead letters or retained delivered messages");

        // Simulate process loss after the durable pre-provider checkpoint.
        std::string interruptedId;
        {
            SqliteOutboxStore store(recoveryPath);
            store.initialize();
            Message interrupted;
            interrupted.id = Poco::UUIDGenerator::defaultGenerator().createRandom().toString();
            interruptedId = interrupted.id;
            interrupted.provider = "recording";
            interrupted.destination = "topic/recovery";
            interrupted.idempotencyKey = "recovery";
            interrupted.payload = "ok";
            interrupted.state = State::delivering;
            interrupted.attempts = 1;
            interrupted.createdMicroseconds = 1;
            interrupted.updatedMicroseconds = 1;
            store.save(interrupted);
        }
        {
            OutboxEngine recovered(
                std::make_unique<SqliteOutboxStore>(recoveryPath), immediatePolicy());
            recovered.initialize();
            auto interrupted = recovered.get(interruptedId);
            require(interrupted.state == State::pending &&
                        interrupted.lastErrorCode == "delivery-interrupted",
                    "in-flight delivery was not recovered to pending");
            Poco::AutoPtr<RecordingProvider> recoveredProvider = new RecordingProvider;
            recovered.attach(recoveredProvider);
            require(recovered.pump() == 1 &&
                        recovered.get(interruptedId).state == State::delivered,
                    "recovered delivery was not acknowledged");
            require(recoveredProvider->calls ==
                        std::vector<std::string>{"recovery:2"},
                    "recovered delivery lost its attempt counter");
        }

        Policy quotaPolicy = immediatePolicy();
        quotaPolicy.maximumActiveMessages = 1;
        OutboxEngine quota(std::make_unique<SqliteOutboxStore>(quotaPath), quotaPolicy);
        quota.initialize();
        quota.enqueue({"missing", "topic/one", "quota-1", "", "ok", 0});
        bool quotaRejected = false;
        try
        {
            quota.enqueue({"missing", "topic/two", "quota-2", "", "ok", 0});
        }
        catch (const Poco::OutOfMemoryException&)
        {
            quotaRejected = true;
        }
        require(quotaRejected, "active-message quota did not apply backpressure");
        }

        removeDatabase(path);
        removeDatabase(recoveryPath);
        removeDatabase(quotaPath);
        std::cout << "store-forward-smoke: PASS\n";
        return 0;
    }
    catch (const Poco::Exception& exception)
    {
        removeDatabase(path);
        removeDatabase(recoveryPath);
        removeDatabase(quotaPath);
        std::cerr << "store-forward-smoke: FAIL: " << exception.displayText() << '\n';
        return 1;
    }
    catch (const std::exception& exception)
    {
        removeDatabase(path);
        removeDatabase(recoveryPath);
        removeDatabase(quotaPath);
        std::cerr << "store-forward-smoke: FAIL: " << exception.what() << '\n';
        return 1;
    }
}
