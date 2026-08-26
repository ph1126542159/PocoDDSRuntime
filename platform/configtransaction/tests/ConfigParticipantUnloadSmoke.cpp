#include "PocoDDS/ConfigTransaction/SqliteTransactionStore.h"
#include "PocoDDS/ConfigTransaction/TransactionEngine.h"

#include <Poco/AutoPtr.h>
#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/TemporaryFile.h>
#include <Poco/UUIDGenerator.h>

#include <atomic>
#include <chrono>
#include <future>
#include <iostream>
#include <memory>
#include <stdexcept>

using namespace std::chrono_literals;

namespace
{
struct State
{
    State(): releaseCommit(releasePromise.get_future().share()) {}
    std::promise<void> commitEntered;
    std::promise<void> releasePromise;
    std::shared_future<void> releaseCommit;
    std::atomic<bool> destroyed{false};
};

class BlockingParticipant final
    : public PocoDDS::ConfigTransaction::ConfigurationParticipantService
{
public:
    explicit BlockingParticipant(std::shared_ptr<State> state): _state(std::move(state)) {}
    ~BlockingParticipant() override { _state->destroyed = true; }

    PocoDDS::ConfigTransaction::ParticipantDescriptor descriptor() const override
    {
        return {"managed-unload", {"managed.value"}, {}};
    }

    PocoDDS::ConfigTransaction::ParticipantResult preflight(
        const PocoDDS::ConfigTransaction::Context&) override
    {
        return PocoDDS::ConfigTransaction::ParticipantResult::accepted();
    }

    PocoDDS::ConfigTransaction::ParticipantResult commit(
        const PocoDDS::ConfigTransaction::Context&) override
    {
        _state->commitEntered.set_value();
        _state->releaseCommit.wait();
        return PocoDDS::ConfigTransaction::ParticipantResult::accepted();
    }

    PocoDDS::ConfigTransaction::ParticipantResult rollback(
        const PocoDDS::ConfigTransaction::Context&) override
    {
        return PocoDDS::ConfigTransaction::ParticipantResult::accepted();
    }

private:
    std::shared_ptr<State> _state;
};
} // namespace

int main()
{
    using namespace PocoDDS::ConfigTransaction;
    try
    {
        Poco::Path path(Poco::TemporaryFile::tempName());
        path.setFileName("pdr-config-participant-unload-" +
            Poco::UUIDGenerator::defaultGenerator().createRandom().toString() + ".sqlite");
        const auto database = path.toString();
        auto state = std::make_shared<State>();
        {
            TransactionEngine engine(std::make_unique<SqliteTransactionStore>(database));
            engine.initialize({{"managed.value", "1"}});
            Poco::AutoPtr<ConfigurationParticipantService> participant =
                new BlockingParticipant(state);
            auto registration = engine.attach(participant);
            participant = nullptr;

            auto apply = std::async(std::launch::async, [&] {
                return engine.apply({"unload-barrier", 1, {{"managed.value", "2"}}});
            });
            state->commitEntered.get_future().wait();
            auto detach = std::async(std::launch::async, [&] { registration.reset(); });
            const auto detachStatus = detach.wait_for(100ms);
            if (detachStatus != std::future_status::timeout)
            {
                state->releasePromise.set_value();
                static_cast<void>(apply.get());
                detach.get();
                throw std::runtime_error(
                    "participant detached while its commit callback was active");
            }

            state->releasePromise.set_value();
            const auto result = apply.get();
            detach.get();
            if (result.status != Status::committed || result.snapshot.generation != 2 ||
                !engine.participantIds().empty() || !state->destroyed.load())
                throw std::runtime_error(
                    "participant unload barrier did not retire the callback safely");
        }
        try { Poco::File(database).remove(); } catch (...) {}
        try { Poco::File(database + "-wal").remove(); } catch (...) {}
        try { Poco::File(database + "-shm").remove(); } catch (...) {}
        std::cout << "CONFIG_PARTICIPANT_UNLOAD_PASS activeCommitWaited=true "
                     "callbackDestroyed=true\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "CONFIG_PARTICIPANT_UNLOAD_FAIL " << exception.what() << '\n';
        return 1;
    }
}
