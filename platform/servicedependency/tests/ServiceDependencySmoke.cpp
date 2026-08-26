#include "PocoDDS/ServiceDependency/ServiceDependency.h"

#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace
{
void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

PocoDDS::ServiceDependency::ProviderDescriptor provider(
    std::string version,
    PocoDDS::ServiceDependency::ProviderState state,
    std::string owner = "pdr.service.schedulerRuntime")
{
    const auto service = owner;
    return {"pdr.scheduling", std::move(version), std::move(owner),
            service, state, {}};
}

PocoDDS::ServiceDependency::RequirementDescriptor requirement(
    std::string owner, bool required = true, bool ownerActive = true)
{
    return {"pdr.scheduling", "[1.0.0,2.0.0)", std::move(owner), required, 1,
            ownerActive};
}
}

int main()
{
    using namespace PocoDDS::ServiceDependency;
    try
    {
        require(matchesVersion("1.4.2", "[1.0.0,2.0.0)"), "valid range mismatch");
        require(!matchesVersion("2.0.0", "[1.0.0,2.0.0)"), "exclusive bound matched");
        require(!validateProvider({"bad contract", "1.0.0", "owner", "service",
                                   ProviderState::ready, {}}),
                "invalid identifier accepted");
        require(!validateRequirement({"contract", "[2.0.0,1.0.0)", "owner", true, 1}),
                "invalid range accepted");

        Catalog catalog;
        require(catalog.replace({}, {requirement("workflow")}), "initial model unchanged");
        auto value = catalog.snapshot();
        require(!value.ready && value.requiredBlocked == 1 &&
                    value.requirements.front().status == RequirementStatus::missing,
                "missing required dependency did not block readiness");

        require(catalog.replace({provider("2.0.0", ProviderState::ready)},
                                {requirement("workflow")}),
                "version mismatch model unchanged");
        value = catalog.snapshot();
        require(value.requirements.front().status == RequirementStatus::versionMismatch,
                "version mismatch was not distinguished");

        require(catalog.replace({provider("1.1.0", ProviderState::degraded)},
                                {requirement("workflow")}),
                "degraded model unchanged");
        value = catalog.snapshot();
        require(value.requirements.front().status == RequirementStatus::providerDegraded,
                "degraded provider was not propagated");

        require(catalog.replace({provider("1.1.0", ProviderState::unavailable)},
                                {requirement("workflow")}),
                "unavailable model unchanged");
        value = catalog.snapshot();
        require(value.requirements.front().status == RequirementStatus::providerUnavailable,
                "unavailable provider was not distinguished");

        const auto beforeRecovery = value.generation;
        require(catalog.replace({provider("1.1.0", ProviderState::ready)},
                                {requirement("workflow"), requirement("optional", false)}),
                "recovery model unchanged");
        value = catalog.snapshot();
        require(value.ready && value.requiredBlocked == 0 && value.optionalUnsatisfied == 0 &&
                    value.generation > beforeRecovery,
                "provider recovery did not restore readiness");
        require(!catalog.replace({provider("1.1.0", ProviderState::ready)},
                                 {requirement("workflow"), requirement("optional", false)}),
                "identical replacement changed generation");
        require(catalog.snapshot().generation == value.generation,
                "identical replacement advanced generation");

        require(catalog.replace({provider("1.1.0", ProviderState::ready)},
                                {requirement("workflow")},
                                {{"broken.bundle", "invalid contract document"}}),
                "declaration error model unchanged");
        value = catalog.snapshot();
        require(!value.ready && value.requiredBlocked == 0 && value.declarationErrors == 1,
                "declaration error did not block readiness independently");

        require(catalog.replace({}, {requirement("sleeping-consumer", true, false)}),
                "inactive consumer model unchanged");
        value = catalog.snapshot();
        require(value.ready && value.requiredBlocked == 0 &&
                    value.activeRequirements == 0 && value.inactiveRequirements == 1,
                "inactive consumer degraded process readiness");
        auto lifecycle = analyzeStart(value, "sleeping-consumer");
        require(!lifecycle.allowed && lifecycle.blockers.size() == 1,
                "start admission ignored an inactive consumer requirement");

        require(catalog.replace({}, {requirement("optional-consumer", false, false)}),
                "optional inactive model unchanged");
        lifecycle = analyzeStart(catalog.snapshot(), "optional-consumer");
        require(lifecycle.allowed && lifecycle.blockers.empty() &&
                    lifecycle.warnings.size() == 1,
                "optional dependency incorrectly blocked start");

        require(catalog.replace(
                    {provider("1.1.0", ProviderState::ready)},
                    {requirement("workflow"), requirement("outbox"),
                     requirement("stopped-consumer", true, false)}),
                "stop impact model unchanged");
        lifecycle = analyzeStop(catalog.snapshot(),
                                "pdr.service.schedulerRuntime");
        require(!lifecycle.allowed && lifecycle.blockers.size() == 2 &&
                    lifecycle.affectedConsumers.size() == 2,
                "active dependent consumers did not block provider stop");

        require(catalog.replace(
                    {provider("1.1.0", ProviderState::ready),
                     provider("1.2.0", ProviderState::ready,
                              "pdr.service.backupScheduler")},
                    {requirement("workflow")}),
                "redundant provider model unchanged");
        lifecycle = analyzeStop(catalog.snapshot(),
                                "pdr.service.schedulerRuntime");
        require(lifecycle.allowed && lifecycle.blockers.empty(),
                "redundant provider did not permit safe stop");

        bool duplicateRejected = false;
        try
        {
            catalog.replace({provider("1.1.0", ProviderState::ready),
                             provider("1.2.0", ProviderState::ready)}, {});
        }
        catch (const std::invalid_argument&)
        {
            duplicateRejected = true;
        }
        require(duplicateRejected, "duplicate provider was accepted");

        std::vector<std::thread> readers;
        for (int index = 0; index < 8; ++index)
            readers.emplace_back([&catalog] {
                for (int iteration = 0; iteration < 1000; ++iteration)
                    require(catalog.snapshot().generation > 0, "concurrent snapshot lost model");
            });
        for (auto& reader : readers) reader.join();

        std::cout << "SERVICE_DEPENDENCY_SMOKE_PASS transitions=9 lifecycleDecisions=4 "
                     "concurrentReaders=8\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "SERVICE_DEPENDENCY_SMOKE_FAIL: " << exception.what() << '\n';
        return 1;
    }
}
