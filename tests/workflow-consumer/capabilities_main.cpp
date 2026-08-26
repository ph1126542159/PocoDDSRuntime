#include <PocoDDS/Capabilities/DecisionLease.h>
#include <PocoDDS/Capabilities/PolicyEngine.h>
#include <PocoDDS/Capabilities/SqlitePolicyStore.h>

#include <filesystem>
#include <iostream>

int main()
{
    using namespace PocoDDS::Capabilities;
    PolicyEngine engine({{"consumer-rule", Effect::allow, "external.consumer",
                          ResourceKind::service, "pdr.service.sample", {Action::use}}});
    const auto decision = engine.decide(
        {"external.consumer", ResourceKind::service, "pdr.service.sample", Action::use});
    if (!decision.allowed || decision.policyDigest.empty()) return 1;
    DecisionLeaseAuthorizer leases(
        [&](const Request& request) { return engine.decide(request); },
        [&] { return engine.snapshot(); });
    const Request leasedRequest{"external.consumer", ResourceKind::service,
                                "pdr.service.sample", Action::use};
    if (!leases.authorize(leasedRequest).allowed ||
        !leases.authorize(leasedRequest).allowed || leases.snapshot().hits != 1)
        return 3;
    const auto database =
        (std::filesystem::temp_directory_path() / "pdr-capabilities-external.sqlite").string();
    {
        SqlitePolicyStore store(database, 10);
        const auto persisted = store.initialize({{"consumer-rule", Effect::allow,
            "external.consumer", ResourceKind::service, "pdr.service.sample", {Action::use}}});
        if (persisted.snapshot.generation != 1 || !store.snapshot().healthy) return 2;
    }
    std::error_code ignored;
    std::filesystem::remove(database, ignored);
    std::filesystem::remove(database + "-wal", ignored);
    std::filesystem::remove(database + "-shm", ignored);
    std::filesystem::remove(database + ".lock", ignored);
    std::cout << "CAPABILITIES_EXTERNAL_CONSUMER_OK\n";
    return 0;
}
