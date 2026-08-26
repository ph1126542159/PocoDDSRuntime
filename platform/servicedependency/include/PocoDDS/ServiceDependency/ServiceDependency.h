#pragma once

#include "PocoDDS/ServiceDependency/Export.h"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::ServiceDependency
{
enum class ProviderState
{
    ready,
    degraded,
    unavailable
};

enum class RequirementStatus
{
    satisfied,
    missing,
    versionMismatch,
    providerDegraded,
    providerUnavailable
};

PDR_SERVICE_DEPENDENCY_API const char* toString(ProviderState state) noexcept;
PDR_SERVICE_DEPENDENCY_API const char* toString(RequirementStatus status) noexcept;

struct ProviderDescriptor
{
    std::string contract;
    std::string version;
    std::string owner;
    std::string serviceName;
    ProviderState state{ProviderState::unavailable};
    std::string detail;
};

struct RequirementDescriptor
{
    std::string contract;
    std::string versionRange;
    std::string owner;
    bool required{true};
    std::size_t minimumProviders{1};
    /// Runtime-derived state. Inactive consumers remain visible for start
    /// admission, but do not degrade process readiness.
    bool ownerActive{true};
};

struct ValidationResult
{
    bool valid{false};
    std::string message;

    explicit operator bool() const noexcept { return valid; }
};

struct DeclarationIssue
{
    std::string owner;
    std::string detail;
};

struct RequirementSnapshot
{
    RequirementDescriptor descriptor;
    RequirementStatus status{RequirementStatus::missing};
    std::size_t declaredProviders{0};
    std::size_t matchingProviders{0};
    std::size_t readyProviders{0};
    std::vector<std::string> matchedProviderServices;
    std::vector<std::string> availableVersions;
    std::string detail;

    [[nodiscard]] bool satisfied() const noexcept
    {
        return status == RequirementStatus::satisfied;
    }
};

struct Snapshot
{
    std::uint64_t generation{0};
    bool ready{true};
    std::size_t requiredBlocked{0};
    std::size_t optionalUnsatisfied{0};
    std::size_t declarationErrors{0};
    std::size_t activeRequirements{0};
    std::size_t inactiveRequirements{0};
    std::vector<ProviderDescriptor> providers;
    std::vector<RequirementSnapshot> requirements;
    std::vector<DeclarationIssue> issues;
};

struct LifecycleFinding
{
    std::string code;
    std::string consumer;
    std::string contract;
    RequirementStatus status{RequirementStatus::missing};
    std::string detail;
};

struct LifecycleDecision
{
    bool allowed{true};
    std::string target;
    std::string action;
    std::string detail;
    std::vector<LifecycleFinding> blockers;
    std::vector<LifecycleFinding> warnings;
    std::vector<std::string> affectedConsumers;
};

PDR_SERVICE_DEPENDENCY_API ValidationResult validateProvider(
    const ProviderDescriptor& provider);
PDR_SERVICE_DEPENDENCY_API ValidationResult validateRequirement(
    const RequirementDescriptor& requirement);
PDR_SERVICE_DEPENDENCY_API bool matchesVersion(
    const std::string& version, const std::string& versionRange);
PDR_SERVICE_DEPENDENCY_API LifecycleDecision analyzeStart(
    const Snapshot& snapshot, const std::string& owner);
PDR_SERVICE_DEPENDENCY_API LifecycleDecision analyzeStop(
    const Snapshot& snapshot, const std::string& providerOwner);

class PDR_SERVICE_DEPENDENCY_API Catalog
{
public:
    Catalog();
    ~Catalog();

    Catalog(const Catalog&) = delete;
    Catalog& operator=(const Catalog&) = delete;

    /// Atomically replaces the complete discovered model. Returns false when
    /// the normalized model is identical and the generation is unchanged.
    bool replace(std::vector<ProviderDescriptor> providers,
                 std::vector<RequirementDescriptor> requirements,
                 std::vector<DeclarationIssue> issues = {});

    [[nodiscard]] Snapshot snapshot() const;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::ServiceDependency
