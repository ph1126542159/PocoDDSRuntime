#include "PocoDDS/Capabilities/DecisionLease.h"

#include <Poco/Exception.h>

#include <algorithm>
#include <chrono>
#include <map>
#include <mutex>
#include <tuple>
#include <utility>

namespace PocoDDS::Capabilities
{
namespace
{
Poco::Int64 monotonicMicroseconds()
{
    return std::chrono::duration_cast<std::chrono::microseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

struct LeaseKey
{
    std::string principal;
    ResourceKind resourceKind{ResourceKind::service};
    std::string resource;
    Action action{Action::discover};

    bool operator<(const LeaseKey& other) const noexcept
    {
        return std::tie(principal, resourceKind, resource, action) <
               std::tie(other.principal, other.resourceKind, other.resource, other.action);
    }
};

LeaseKey keyFor(const Request& request)
{
    return {request.principal, request.resourceKind, request.resource, request.action};
}
} // namespace

class DecisionLeaseAuthorizer::Impl
{
public:
    struct Entry
    {
        Decision decision;
        Poco::Int64 expiresMicroseconds{0};
        Poco::UInt64 remainingUses{0};
        Poco::UInt64 lastAccess{0};
    };

    Impl(Authorizer authorize, SnapshotProvider snapshot, DecisionLeaseOptions value,
         HealthProvider health, Clock time)
        : authorizer(std::move(authorize)), snapshotProvider(std::move(snapshot)),
          options(value), healthProvider(std::move(health)), clock(std::move(time))
    {
        if (!authorizer)
            throw Poco::InvalidArgumentException("Decision lease authorizer is required");
        if (!snapshotProvider)
            throw Poco::InvalidArgumentException("Decision lease snapshot provider is required");
        if (options.durationMilliseconds == 0 || options.durationMilliseconds > 60000)
            throw Poco::InvalidArgumentException(
                "Decision lease duration must contain 1..60000 milliseconds");
        if (options.maximumUses == 0 || options.maximumUses > 1000000)
            throw Poco::InvalidArgumentException(
                "Decision lease maximum uses must contain 1..1000000 operations");
        if (options.capacity == 0 || options.capacity > 1000000)
            throw Poco::InvalidArgumentException(
                "Decision lease capacity must contain 1..1000000 entries");
        if (!healthProvider) healthProvider = [] { return true; };
        if (!clock) clock = monotonicMicroseconds;
    }

    void requireHealthy() const
    {
        if (!healthProvider())
            throw Poco::IllegalStateException(
                "Capability decision lease authority is unavailable");
    }

    void synchronizeGeneration(Poco::UInt64 generation) const
    {
        if (observedGeneration == 0)
        {
            observedGeneration = generation;
            return;
        }
        if (observedGeneration == generation) return;
        invalidated += static_cast<Poco::UInt64>(entries.size());
        entries.clear();
        observedGeneration = generation;
    }

    PolicySnapshot currentPolicy() const
    {
        const auto current = snapshotProvider();
        if (current.generation == 0 || current.digest.empty())
            throw Poco::IllegalStateException(
                "Decision lease policy snapshot is incomplete");
        return current;
    }

    Authorizer authorizer;
    SnapshotProvider snapshotProvider;
    DecisionLeaseOptions options;
    HealthProvider healthProvider;
    Clock clock;
    mutable std::mutex mutex;
    mutable std::map<LeaseKey, Entry> entries;
    mutable Poco::UInt64 observedGeneration{0};
    mutable Poco::UInt64 sequence{0};
    mutable Poco::UInt64 hits{0};
    mutable Poco::UInt64 misses{0};
    mutable Poco::UInt64 issued{0};
    mutable Poco::UInt64 denied{0};
    mutable Poco::UInt64 expired{0};
    mutable Poco::UInt64 invalidated{0};
    mutable Poco::UInt64 evicted{0};
};

DecisionLeaseAuthorizer::DecisionLeaseAuthorizer(
    Authorizer authorizer, SnapshotProvider snapshotProvider, DecisionLeaseOptions options,
    HealthProvider healthProvider, Clock clock)
    : _impl(std::make_unique<Impl>(std::move(authorizer), std::move(snapshotProvider), options,
                                   std::move(healthProvider), std::move(clock))) {}

DecisionLeaseAuthorizer::~DecisionLeaseAuthorizer() = default;

Decision DecisionLeaseAuthorizer::authorize(const Request& request) const
{
    _impl->requireHealthy();
    if (!_impl->options.enabled)
    {
        {
            std::lock_guard<std::mutex> lock(_impl->mutex);
            ++_impl->misses;
        }
        const auto decision = _impl->authorizer(request);
        if (!decision.allowed)
        {
            std::lock_guard<std::mutex> lock(_impl->mutex);
            ++_impl->denied;
        }
        return decision;
    }

    const auto policy = _impl->currentPolicy();
    const auto now = _impl->clock();
    const auto key = keyFor(request);
    {
        std::lock_guard<std::mutex> lock(_impl->mutex);
        _impl->synchronizeGeneration(policy.generation);
        const auto found = _impl->entries.find(key);
        if (found != _impl->entries.end())
        {
            if (now >= found->second.expiresMicroseconds)
            {
                _impl->entries.erase(found);
                ++_impl->expired;
            }
            else if (found->second.remainingUses > 0)
            {
                auto decision = found->second.decision;
                --found->second.remainingUses;
                found->second.lastAccess = ++_impl->sequence;
                ++_impl->hits;
                if (found->second.remainingUses == 0) _impl->entries.erase(found);
                return decision;
            }
        }
        ++_impl->misses;
    }

    Decision decision;
    PolicySnapshot stablePolicy;
    bool stable = false;
    for (int attempt = 0; attempt < 3; ++attempt)
    {
        decision = _impl->authorizer(request);
        _impl->requireHealthy();
        stablePolicy = _impl->currentPolicy();
        if (decision.policyGeneration == stablePolicy.generation &&
            decision.policyDigest == stablePolicy.digest)
        {
            stable = true;
            break;
        }
    }
    if (!stable)
        throw Poco::IllegalStateException(
            "Capability policy changed repeatedly while issuing a decision lease");

    if (!decision.allowed)
    {
        std::lock_guard<std::mutex> lock(_impl->mutex);
        _impl->synchronizeGeneration(stablePolicy.generation);
        ++_impl->denied;
        return decision;
    }

    if (_impl->options.maximumUses > 1)
    {
        std::lock_guard<std::mutex> lock(_impl->mutex);
        _impl->synchronizeGeneration(stablePolicy.generation);
        const auto existing = _impl->entries.find(key);
        if (existing == _impl->entries.end() &&
            _impl->entries.size() >= _impl->options.capacity)
        {
            const auto oldest = std::min_element(
                _impl->entries.begin(), _impl->entries.end(),
                [](const auto& left, const auto& right) {
                    return left.second.lastAccess < right.second.lastAccess;
                });
            if (oldest != _impl->entries.end())
            {
                _impl->entries.erase(oldest);
                ++_impl->evicted;
            }
        }
        const auto duration = static_cast<Poco::Int64>(
            _impl->options.durationMilliseconds * 1000);
        _impl->entries[key] = {decision, _impl->clock() + duration,
                               _impl->options.maximumUses - 1, ++_impl->sequence};
        ++_impl->issued;
    }
    return decision;
}

void DecisionLeaseAuthorizer::require(const Request& request) const
{
    const auto decision = authorize(request);
    if (!decision.allowed)
        throw Poco::NoPermissionException(decision.code, decision.explanation);
}

void DecisionLeaseAuthorizer::invalidate() noexcept
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    _impl->invalidated += static_cast<Poco::UInt64>(_impl->entries.size());
    _impl->entries.clear();
    _impl->observedGeneration = 0;
}

DecisionLeaseSnapshot DecisionLeaseAuthorizer::snapshot() const noexcept
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    return {_impl->options.enabled, _impl->observedGeneration, _impl->entries.size(),
            _impl->hits, _impl->misses, _impl->issued, _impl->denied, _impl->expired,
            _impl->invalidated, _impl->evicted};
}
} // namespace PocoDDS::Capabilities
