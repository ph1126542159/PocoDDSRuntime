#pragma once

#include "PocoDDS/Capabilities/PolicyEngine.h"

#include <functional>
#include <memory>

namespace PocoDDS::Capabilities
{
struct DecisionLeaseOptions
{
    bool enabled{true};
    Poco::UInt64 durationMilliseconds{250};
    Poco::UInt64 maximumUses{1024};
    std::size_t capacity{4096};
};

struct DecisionLeaseSnapshot
{
    bool enabled{false};
    Poco::UInt64 policyGeneration{0};
    std::size_t entries{0};
    Poco::UInt64 hits{0};
    Poco::UInt64 misses{0};
    Poco::UInt64 issued{0};
    Poco::UInt64 denied{0};
    Poco::UInt64 expired{0};
    Poco::UInt64 invalidated{0};
    Poco::UInt64 evicted{0};
};

class PDR_CAPABILITIES_API DecisionLeaseAuthorizer
{
public:
    using Authorizer = std::function<Decision(const Request&)>;
    using SnapshotProvider = std::function<PolicySnapshot()>;
    using HealthProvider = std::function<bool()>;
    using Clock = std::function<Poco::Int64()>;

    DecisionLeaseAuthorizer(Authorizer authorizer,
                            SnapshotProvider snapshotProvider,
                            DecisionLeaseOptions options = {},
                            HealthProvider healthProvider = {},
                            Clock clock = {});
    ~DecisionLeaseAuthorizer();
    DecisionLeaseAuthorizer(const DecisionLeaseAuthorizer&) = delete;
    DecisionLeaseAuthorizer& operator=(const DecisionLeaseAuthorizer&) = delete;

    Decision authorize(const Request& request) const;
    void require(const Request& request) const;
    void invalidate() noexcept;
    DecisionLeaseSnapshot snapshot() const noexcept;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Capabilities
