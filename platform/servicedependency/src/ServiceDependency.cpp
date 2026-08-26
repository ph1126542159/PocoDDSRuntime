#include "PocoDDS/ServiceDependency/ServiceDependency.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <limits>
#include <mutex>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <tuple>
#include <utility>

namespace PocoDDS::ServiceDependency
{
namespace
{
struct Version
{
    std::array<unsigned, 3> parts{};
};

bool operator<(const Version& lhs, const Version& rhs) noexcept
{
    return lhs.parts < rhs.parts;
}

bool operator==(const Version& lhs, const Version& rhs) noexcept
{
    return lhs.parts == rhs.parts;
}

std::string trim(std::string value)
{
    const auto first = std::find_if_not(value.begin(), value.end(),
                                        [](unsigned char ch) { return std::isspace(ch); });
    const auto last = std::find_if_not(value.rbegin(), value.rend(),
                                       [](unsigned char ch) { return std::isspace(ch); }).base();
    if (first >= last) return {};
    return std::string(first, last);
}

std::optional<Version> parseVersion(const std::string& raw)
{
    const auto value = trim(raw);
    if (value.empty()) return std::nullopt;
    Version result;
    std::size_t begin = 0;
    for (std::size_t index = 0; index < result.parts.size(); ++index)
    {
        const auto end = value.find('.', begin);
        const auto token = value.substr(begin, end == std::string::npos
                                                   ? std::string::npos
                                                   : end - begin);
        if (token.empty() || !std::all_of(token.begin(), token.end(),
                                         [](unsigned char ch) { return std::isdigit(ch); }))
            return std::nullopt;
        try
        {
            const auto parsed = std::stoull(token);
            if (parsed > std::numeric_limits<unsigned>::max()) return std::nullopt;
            result.parts[index] = static_cast<unsigned>(parsed);
        }
        catch (...)
        {
            return std::nullopt;
        }
        if (index + 1 == result.parts.size())
        {
            if (end != std::string::npos) return std::nullopt;
        }
        else
        {
            if (end == std::string::npos) return std::nullopt;
            begin = end + 1;
        }
    }
    return result;
}

struct Constraint
{
    std::optional<Version> lower;
    std::optional<Version> upper;
    bool includeLower{true};
    bool includeUpper{true};
};

std::optional<Constraint> parseConstraint(const std::string& raw)
{
    const auto value = trim(raw);
    if (value.empty()) return std::nullopt;
    if (value.front() != '[' && value.front() != '(')
    {
        const auto exact = parseVersion(value);
        if (!exact) return std::nullopt;
        return Constraint{exact, exact, true, true};
    }
    if ((value.back() != ']' && value.back() != ')') || value.size() < 3)
        return std::nullopt;
    const auto comma = value.find(',');
    if (comma == std::string::npos || value.find(',', comma + 1) != std::string::npos)
        return std::nullopt;
    Constraint result;
    result.includeLower = value.front() == '[';
    result.includeUpper = value.back() == ']';
    const auto lowerText = trim(value.substr(1, comma - 1));
    const auto upperText = trim(value.substr(comma + 1, value.size() - comma - 2));
    if (!lowerText.empty())
    {
        result.lower = parseVersion(lowerText);
        if (!result.lower) return std::nullopt;
    }
    if (!upperText.empty())
    {
        result.upper = parseVersion(upperText);
        if (!result.upper) return std::nullopt;
    }
    if (!result.lower && !result.upper) return std::nullopt;
    if (result.lower && result.upper)
    {
        if (*result.upper < *result.lower) return std::nullopt;
        if (*result.lower == *result.upper &&
            (!result.includeLower || !result.includeUpper))
            return std::nullopt;
    }
    return result;
}

bool matches(const Version& version, const Constraint& constraint) noexcept
{
    if (constraint.lower)
    {
        if (version < *constraint.lower) return false;
        if (!constraint.includeLower && version == *constraint.lower) return false;
    }
    if (constraint.upper)
    {
        if (*constraint.upper < version) return false;
        if (!constraint.includeUpper && version == *constraint.upper) return false;
    }
    return true;
}

bool validIdentifier(const std::string& value, std::size_t maximum)
{
    return !value.empty() && value.size() <= maximum &&
           std::all_of(value.begin(), value.end(), [](unsigned char ch) {
               return std::isalnum(ch) || ch == '.' || ch == '_' || ch == '-' || ch == ':';
           });
}

bool same(const ProviderDescriptor& lhs, const ProviderDescriptor& rhs)
{
    return std::tie(lhs.contract, lhs.version, lhs.owner, lhs.serviceName,
                    lhs.state, lhs.detail) ==
           std::tie(rhs.contract, rhs.version, rhs.owner, rhs.serviceName,
                    rhs.state, rhs.detail);
}

bool same(const RequirementDescriptor& lhs, const RequirementDescriptor& rhs)
{
    return std::tie(lhs.contract, lhs.versionRange, lhs.owner, lhs.required,
                    lhs.minimumProviders, lhs.ownerActive) ==
           std::tie(rhs.contract, rhs.versionRange, rhs.owner, rhs.required,
                    rhs.minimumProviders, rhs.ownerActive);
}

bool same(const DeclarationIssue& lhs, const DeclarationIssue& rhs)
{
    return std::tie(lhs.owner, lhs.detail) == std::tie(rhs.owner, rhs.detail);
}

template <typename Value, typename Compare>
bool sameVector(const std::vector<Value>& lhs, const std::vector<Value>& rhs,
                Compare compare)
{
    return lhs.size() == rhs.size() &&
           std::equal(lhs.begin(), lhs.end(), rhs.begin(), compare);
}

std::string providerLabel(const ProviderDescriptor& provider)
{
    return provider.owner + "/" + provider.serviceName + "@" + provider.version;
}

RequirementSnapshot evaluateRequirement(
    const RequirementDescriptor& requirement,
    const std::vector<ProviderDescriptor>& providers)
{
    RequirementSnapshot item;
    item.descriptor = requirement;
    std::size_t degraded = 0;
    for (const auto& provider : providers)
    {
        if (provider.contract != requirement.contract) continue;
        ++item.declaredProviders;
        item.availableVersions.push_back(provider.version);
        if (!matchesVersion(provider.version, requirement.versionRange)) continue;
        ++item.matchingProviders;
        item.matchedProviderServices.push_back(providerLabel(provider));
        if (provider.state == ProviderState::ready) ++item.readyProviders;
        if (provider.state == ProviderState::degraded) ++degraded;
    }
    std::sort(item.availableVersions.begin(), item.availableVersions.end());
    item.availableVersions.erase(
        std::unique(item.availableVersions.begin(), item.availableVersions.end()),
        item.availableVersions.end());
    if (item.readyProviders >= requirement.minimumProviders)
    {
        item.status = RequirementStatus::satisfied;
        item.detail = std::to_string(item.readyProviders) + "/" +
                      std::to_string(requirement.minimumProviders) +
                      " required provider(s) ready";
    }
    else if (item.declaredProviders == 0)
    {
        item.status = RequirementStatus::missing;
        item.detail = "no provider declares contract " + requirement.contract;
    }
    else if (item.matchingProviders == 0)
    {
        item.status = RequirementStatus::versionMismatch;
        item.detail = "declared provider versions do not match " +
                      requirement.versionRange;
    }
    else if (degraded > 0)
    {
        item.status = RequirementStatus::providerDegraded;
        item.detail = "matching provider is degraded";
    }
    else
    {
        item.status = RequirementStatus::providerUnavailable;
        item.detail = "matching provider Bundle or service is unavailable";
    }
    return item;
}

LifecycleFinding finding(const std::string& code,
                         const RequirementSnapshot& requirement)
{
    return {code, requirement.descriptor.owner,
            requirement.descriptor.contract, requirement.status,
            requirement.detail};
}

void finalize(LifecycleDecision& decision)
{
    decision.allowed = decision.blockers.empty();
    for (const auto& blocker : decision.blockers)
        decision.affectedConsumers.push_back(blocker.consumer);
    for (const auto& warning : decision.warnings)
        decision.affectedConsumers.push_back(warning.consumer);
    std::sort(decision.affectedConsumers.begin(),
              decision.affectedConsumers.end());
    decision.affectedConsumers.erase(
        std::unique(decision.affectedConsumers.begin(),
                    decision.affectedConsumers.end()),
        decision.affectedConsumers.end());
    if (decision.allowed)
        decision.detail = decision.warnings.empty()
            ? "lifecycle action satisfies all active required dependencies"
            : "lifecycle action is allowed with optional dependency impact";
    else
        decision.detail = std::to_string(decision.blockers.size()) +
                          (decision.action == "stop"
                               ? " active Consumer dependency blocker(s)"
                               : " required dependency blocker(s)");
}
} // namespace

const char* toString(ProviderState state) noexcept
{
    switch (state)
    {
    case ProviderState::ready: return "ready";
    case ProviderState::degraded: return "degraded";
    case ProviderState::unavailable: return "unavailable";
    }
    return "unavailable";
}

const char* toString(RequirementStatus status) noexcept
{
    switch (status)
    {
    case RequirementStatus::satisfied: return "satisfied";
    case RequirementStatus::missing: return "missing";
    case RequirementStatus::versionMismatch: return "versionMismatch";
    case RequirementStatus::providerDegraded: return "providerDegraded";
    case RequirementStatus::providerUnavailable: return "providerUnavailable";
    }
    return "missing";
}

ValidationResult validateProvider(const ProviderDescriptor& provider)
{
    if (!validIdentifier(provider.contract, 128))
        return {false, "contract must contain 1..128 identifier characters"};
    if (!validIdentifier(provider.owner, 128))
        return {false, "owner must contain 1..128 identifier characters"};
    if (!validIdentifier(provider.serviceName, 192))
        return {false, "serviceName must contain 1..192 identifier characters"};
    if (!parseVersion(provider.version))
        return {false, "version must be numeric major.minor.patch"};
    if (provider.detail.size() > 512)
        return {false, "provider detail must not exceed 512 characters"};
    return {true, {}};
}

ValidationResult validateRequirement(const RequirementDescriptor& requirement)
{
    if (!validIdentifier(requirement.contract, 128))
        return {false, "contract must contain 1..128 identifier characters"};
    if (!validIdentifier(requirement.owner, 128))
        return {false, "owner must contain 1..128 identifier characters"};
    if (requirement.versionRange.size() > 128 || !parseConstraint(requirement.versionRange))
        return {false, "versionRange must be an exact version or interval"};
    if (requirement.minimumProviders == 0 || requirement.minimumProviders > 64)
        return {false, "minimumProviders must be between 1 and 64"};
    return {true, {}};
}

bool matchesVersion(const std::string& version, const std::string& versionRange)
{
    const auto parsedVersion = parseVersion(version);
    const auto parsedConstraint = parseConstraint(versionRange);
    return parsedVersion && parsedConstraint && matches(*parsedVersion, *parsedConstraint);
}

LifecycleDecision analyzeStart(const Snapshot& snapshot, const std::string& owner)
{
    LifecycleDecision decision;
    decision.target = owner;
    decision.action = "start";
    for (const auto& issue : snapshot.issues)
    {
        if (issue.owner != owner) continue;
        decision.blockers.push_back({
            "DEPENDENCY_DECLARATION_INVALID", owner, "", RequirementStatus::missing,
            issue.detail});
    }
    for (const auto& requirement : snapshot.requirements)
    {
        if (requirement.descriptor.owner != owner || requirement.satisfied()) continue;
        if (requirement.descriptor.required)
            decision.blockers.push_back(finding(
                "DEPENDENCY_REQUIRED_UNSATISFIED", requirement));
        else
            decision.warnings.push_back(finding(
                "OPTIONAL_DEPENDENCY_UNSATISFIED", requirement));
    }
    finalize(decision);
    return decision;
}

LifecycleDecision analyzeStop(const Snapshot& snapshot,
                              const std::string& providerOwner)
{
    LifecycleDecision decision;
    decision.target = providerOwner;
    decision.action = "stop";
    std::vector<ProviderDescriptor> remaining = snapshot.providers;
    bool declaresProvider = false;
    for (auto& provider : remaining)
    {
        if (provider.owner != providerOwner) continue;
        declaresProvider = true;
        provider.state = ProviderState::unavailable;
        provider.detail = "provider is being evaluated for stop";
    }
    if (declaresProvider)
    {
        for (const auto& current : snapshot.requirements)
        {
            if (!current.descriptor.ownerActive ||
                current.descriptor.owner == providerOwner ||
                !current.satisfied())
                continue;
            const auto after = evaluateRequirement(current.descriptor, remaining);
            if (after.satisfied()) continue;
            if (current.descriptor.required)
                decision.blockers.push_back(finding(
                    "ACTIVE_CONSUMER_DEPENDENCY_IMPACT", after));
            else
                decision.warnings.push_back(finding(
                    "OPTIONAL_CONSUMER_DEPENDENCY_IMPACT", after));
        }
    }
    finalize(decision);
    return decision;
}

class Catalog::Impl
{
public:
    bool replace(std::vector<ProviderDescriptor> providers,
                 std::vector<RequirementDescriptor> requirements,
                 std::vector<DeclarationIssue> issues)
    {
        if (providers.size() > 1024 || requirements.size() > 1024 || issues.size() > 1024)
            throw std::invalid_argument("service dependency model exceeds 1024 declarations");
        std::set<std::tuple<std::string, std::string, std::string>> providerKeys;
        for (const auto& provider : providers)
        {
            const auto validation = validateProvider(provider);
            if (!validation) throw std::invalid_argument(validation.message);
            if (!providerKeys.emplace(provider.owner, provider.contract,
                                      provider.serviceName).second)
                throw std::invalid_argument("duplicate provider declaration");
        }
        std::set<std::pair<std::string, std::string>> requirementKeys;
        for (const auto& requirement : requirements)
        {
            const auto validation = validateRequirement(requirement);
            if (!validation) throw std::invalid_argument(validation.message);
            if (!requirementKeys.emplace(requirement.owner, requirement.contract).second)
                throw std::invalid_argument("duplicate requirement declaration");
        }
        for (const auto& issue : issues)
        {
            if (!validIdentifier(issue.owner, 128) || issue.detail.empty() ||
                issue.detail.size() > 1024)
                throw std::invalid_argument("invalid service dependency declaration issue");
        }
        std::sort(providers.begin(), providers.end(), [](const auto& lhs, const auto& rhs) {
            return std::tie(lhs.contract, lhs.owner, lhs.serviceName, lhs.version) <
                   std::tie(rhs.contract, rhs.owner, rhs.serviceName, rhs.version);
        });
        std::sort(requirements.begin(), requirements.end(),
                  [](const auto& lhs, const auto& rhs) {
            return std::tie(lhs.owner, lhs.contract) < std::tie(rhs.owner, rhs.contract);
        });
        std::sort(issues.begin(), issues.end(), [](const auto& lhs, const auto& rhs) {
            return std::tie(lhs.owner, lhs.detail) < std::tie(rhs.owner, rhs.detail);
        });
        std::lock_guard<std::mutex> lock(_mutex);
        if (sameVector(_providers, providers,
                       [](const auto& lhs, const auto& rhs) { return same(lhs, rhs); }) &&
            sameVector(_requirements, requirements,
                       [](const auto& lhs, const auto& rhs) { return same(lhs, rhs); }) &&
            sameVector(_issues, issues,
                       [](const auto& lhs, const auto& rhs) { return same(lhs, rhs); }))
            return false;
        _providers = std::move(providers);
        _requirements = std::move(requirements);
        _issues = std::move(issues);
        ++_generation;
        return true;
    }

    Snapshot snapshot() const
    {
        std::vector<ProviderDescriptor> providers;
        std::vector<RequirementDescriptor> requirements;
        std::vector<DeclarationIssue> issues;
        std::uint64_t generation = 0;
        {
            std::lock_guard<std::mutex> lock(_mutex);
            providers = _providers;
            requirements = _requirements;
            issues = _issues;
            generation = _generation;
        }
        Snapshot result;
        result.generation = generation;
        result.providers = providers;
        result.issues = std::move(issues);
        result.declarationErrors = result.issues.size();
        for (const auto& requirement : requirements)
        {
            auto item = evaluateRequirement(requirement, providers);
            if (requirement.ownerActive) ++result.activeRequirements;
            else ++result.inactiveRequirements;
            if (requirement.ownerActive && !item.satisfied())
            {
                if (requirement.required) ++result.requiredBlocked;
                else ++result.optionalUnsatisfied;
            }
            result.requirements.push_back(std::move(item));
        }
        result.ready = result.requiredBlocked == 0 && result.declarationErrors == 0;
        return result;
    }

private:
    mutable std::mutex _mutex;
    std::vector<ProviderDescriptor> _providers;
    std::vector<RequirementDescriptor> _requirements;
    std::vector<DeclarationIssue> _issues;
    std::uint64_t _generation{0};
};

Catalog::Catalog(): _impl(std::make_unique<Impl>()) {}
Catalog::~Catalog() = default;

bool Catalog::replace(std::vector<ProviderDescriptor> providers,
                      std::vector<RequirementDescriptor> requirements,
                      std::vector<DeclarationIssue> issues)
{
    return _impl->replace(std::move(providers), std::move(requirements),
                          std::move(issues));
}

Snapshot Catalog::snapshot() const
{
    return _impl->snapshot();
}
} // namespace PocoDDS::ServiceDependency
