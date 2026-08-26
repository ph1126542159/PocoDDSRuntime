#include "PocoDDS/ServiceDependency/ServiceDependency.h"

int main()
{
    using namespace PocoDDS::ServiceDependency;
    Catalog catalog;
    ProviderDescriptor provider{
        "example.contract", "1.2.0", "example.provider",
        "example.service", ProviderState::ready, "external consumer"};
    RequirementDescriptor requirement{
        "example.contract", "[1.0.0,2.0.0)", "example.consumer", true, 1};
    if (!validateProvider(provider) || !validateRequirement(requirement)) return 1;
    if (!catalog.replace({provider}, {requirement})) return 2;
    const auto snapshot = catalog.snapshot();
    if (!snapshot.ready || snapshot.requiredBlocked != 0 ||
        snapshot.requirements.size() != 1 ||
        !snapshot.requirements.front().satisfied())
        return 3;
    const auto stop = analyzeStop(snapshot, "example.provider");
    if (stop.allowed || stop.blockers.size() != 1 ||
        stop.affectedConsumers != std::vector<std::string>{"example.consumer"})
        return 4;
    requirement.ownerActive = false;
    if (!catalog.replace({}, {requirement})) return 5;
    const auto inactive = catalog.snapshot();
    if (!inactive.ready || inactive.inactiveRequirements != 1 ||
        analyzeStart(inactive, "example.consumer").allowed)
        return 6;
    return 0;
}
