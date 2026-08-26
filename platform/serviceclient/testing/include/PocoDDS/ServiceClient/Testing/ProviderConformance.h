#pragma once

#include "PocoDDS/ServiceClient/ServiceInvocationProvider.h"
#include "PocoDDS/ServiceClient/Testing/Export.h"

#include <chrono>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace PocoDDS::ServiceClient::Testing
{
struct ProviderConformanceExpectations
{
    std::string providerId;
    std::string protocol;
    ProviderInvocationRequest validRequest;
    std::function<bool(const AttemptResult&)> validResult;
    /// Fixture-owned count of outbound calls or equivalent observable side
    /// effects. Negative probes must not increment it; the valid probe must
    /// increment it exactly once.
    std::function<std::uint64_t()> observedInvocations;
    std::chrono::milliseconds maximumCallDuration{5000};
};

struct ProviderConformanceReport
{
    std::string providerId;
    std::string protocol;
    std::vector<std::string> passedChecks;
};

struct ProviderConformanceResult
{
    bool passed{false};
    ProviderConformanceReport report;
    std::string failedCheck;
    std::string detail;

    explicit operator bool() const noexcept { return passed; }
};

/// Runs the transport-neutral contract every invocation Provider must satisfy.
/// Protocol teams supply one valid fixture request and an observable outbound
/// invocation counter; the TCK owns all negative and mutation probes.
PDR_SERVICE_CLIENT_TESTING_API ProviderConformanceResult
runProviderConformance(
    ServiceInvocationProvider& provider,
    const ProviderConformanceExpectations& expectations);
} // namespace PocoDDS::ServiceClient::Testing
