#include "PocoDDS/Capabilities/PolicyEngine.h"
#include "PocoDDS/ConfigTransaction/ConfigurationParticipantService.h"
#include "PocoDDS/ConfigTransaction/SqliteTransactionStore.h"
#include "PocoDDS/ConfigTransaction/TransactionEngine.h"

#include <Poco/AutoPtr.h>
#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/TemporaryFile.h>
#include <Poco/UUIDGenerator.h>

#include <iostream>
#include <memory>

namespace
{
class Participant final
    : public PocoDDS::ConfigTransaction::ConfigurationParticipantService
{
public:
    PocoDDS::ConfigTransaction::ParticipantDescriptor descriptor() const override
    {
        return {"logging-test", {"logging"}, {}};
    }
    PocoDDS::ConfigTransaction::ParticipantResult preflight(
        const PocoDDS::ConfigTransaction::Context&) override
    {
        return PocoDDS::ConfigTransaction::ParticipantResult::accepted();
    }
    PocoDDS::ConfigTransaction::ParticipantResult commit(
        const PocoDDS::ConfigTransaction::Context&) override
    {
        return PocoDDS::ConfigTransaction::ParticipantResult::accepted();
    }
    PocoDDS::ConfigTransaction::ParticipantResult rollback(
        const PocoDDS::ConfigTransaction::Context&) override
    {
        return PocoDDS::ConfigTransaction::ParticipantResult::accepted();
    }
};
} // namespace

int main()
{
    using namespace PocoDDS::Capabilities;
    using namespace PocoDDS::ConfigTransaction;
    try
    {
        Poco::Path path(Poco::TemporaryFile::tempName());
        path.setFileName("pdr-config-capability-hook-" +
            Poco::UUIDGenerator::defaultGenerator().createRandom().toString() + ".sqlite");
        PolicyEngine policy({{"allow-operator-logging", Effect::allow, "operator",
            ResourceKind::configuration, "logging.*", {Action::write}}});
        {
            TransactionEngine engine(
                std::make_unique<SqliteTransactionStore>(path.toString()),
                {{}, {}, [&](const std::string& principal, const std::vector<std::string>& keys) {
                    for (const auto& key : keys)
                        policy.require({principal, ResourceKind::configuration, key, Action::write});
                }});
            engine.initialize({{"logging.level", "information"}});
            auto registration = engine.attach(
                Poco::AutoPtr<ConfigurationParticipantService>(new Participant));

            bool denied = false;
            try
            {
                static_cast<void>(engine.apply(
                    {"same-request", 1, {{"logging.level", "debug"}}, "untrusted.bundle"}));
            }
            catch (const Poco::NoPermissionException&) { denied = true; }
            if (!denied || engine.current().generation != 1)
                throw std::runtime_error("unauthorized configuration write was not rejected");

            const auto committed = engine.apply(
                {"same-request", 1, {{"logging.level", "debug"}}, "operator"});
            if (committed.status != Status::committed || committed.snapshot.generation != 2)
                throw std::runtime_error("authorized configuration write did not commit");

            bool replayDenied = false;
            try
            {
                static_cast<void>(engine.apply(
                    {"same-request", 1, {{"logging.level", "debug"}}, "untrusted.bundle"}));
            }
            catch (const Poco::NoPermissionException&) { replayDenied = true; }
            if (!replayDenied)
                throw std::runtime_error("idempotent replay bypassed authorization");
        }

        if (Poco::File(path).exists()) Poco::File(path).remove();
        std::cout << "CONFIG_CAPABILITY_HOOK_OK\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "CONFIG_CAPABILITY_HOOK_FAILED: " << exception.what() << '\n';
        return 1;
    }
}
