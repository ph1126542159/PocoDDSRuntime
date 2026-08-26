#include "PocoDDS/ServiceDirectory/Directory.h"

#include <Poco/Exception.h>

#include <algorithm>
#include <iterator>
#include <map>
#include <mutex>
#include <set>
#include <tuple>
#include <utility>

namespace PocoDDS::ServiceDirectory
{
namespace
{
using TimePoint = std::chrono::steady_clock::time_point;
using Key = std::pair<std::string, std::string>;

bool safeText(const std::string& value, std::size_t maximum, bool required)
{
    if ((required && value.empty()) || value.size() > maximum) return false;
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return character >= 0x21 && character <= 0x7e;
    });
}

bool sortedUnique(const std::vector<std::string>& values)
{
    return std::is_sorted(values.begin(), values.end()) &&
           std::adjacent_find(values.begin(), values.end()) == values.end();
}

std::string validate(const Advertisement& value)
{
    if (!safeText(value.serviceName, 128, true))
        return "serviceName must contain 1..128 visible ASCII characters";
    if (!safeText(value.instanceId, 128, true))
        return "instanceId must contain 1..128 visible ASCII characters";
    if (!safeText(value.runtimeId, 128, true))
        return "runtimeId must contain 1..128 visible ASCII characters";
    if (value.runtimeIncarnation == 0)
        return "runtimeIncarnation must be greater than zero";
    if (value.revision == 0) return "revision must be greater than zero";
    if (!safeText(value.endpoint, 512, true))
        return "endpoint must contain 1..512 visible ASCII characters";
    if (!safeText(value.protocol, 32, true))
        return "protocol must contain 1..32 visible ASCII characters";
    if (!safeText(value.zone, 64, false))
        return "zone must contain at most 64 visible ASCII characters";
    if (value.tags.size() > 64) return "tag count exceeds 64";
    if (!sortedUnique(value.tags)) return "tags must be sorted and unique";
    for (const auto& tag : value.tags)
        if (!safeText(tag, 64, true))
            return "tag must contain 1..64 visible ASCII characters";
    return {};
}

std::string validate(const RouteRequest& request)
{
    if (!safeText(request.serviceName, 128, true))
        return "serviceName must contain 1..128 visible ASCII characters";
    if (!safeText(request.routingKey, 256, false))
        return "routingKey must contain at most 256 visible ASCII characters";
    if (!safeText(request.localRuntimeId, 128, false))
        return "localRuntimeId must contain at most 128 visible ASCII characters";
    if (request.requiredTags.size() > 64 || !sortedUnique(request.requiredTags))
        return "requiredTags must be sorted, unique and bounded to 64";
    for (const auto& tag : request.requiredTags)
        if (!safeText(tag, 64, true))
            return "required tag must contain 1..64 visible ASCII characters";
    if (request.excludedInstances.size() > 256 ||
        !std::is_sorted(request.excludedInstances.begin(),
                        request.excludedInstances.end()) ||
        std::adjacent_find(request.excludedInstances.begin(),
                           request.excludedInstances.end()) !=
            request.excludedInstances.end())
        return "excludedInstances must be sorted, unique and bounded to 256";
    for (const auto& instance : request.excludedInstances)
        if (!safeText(instance.instanceId, 128, true) ||
            !safeText(instance.runtimeId, 128, true) ||
            instance.runtimeIncarnation == 0)
            return "excluded instance identity is invalid";
    return {};
}

std::chrono::milliseconds age(TimePoint now, TimePoint lastSeen)
{
    if (now <= lastSeen) return std::chrono::milliseconds{0};
    return std::chrono::duration_cast<std::chrono::milliseconds>(now - lastSeen);
}

InstanceState instanceState(const Advertisement& advertisement)
{
    return advertisement.state == AdvertisedState::ready
               ? InstanceState::ready
               : InstanceState::draining;
}

std::uint64_t fnv1a(const std::string& value)
{
    std::uint64_t hash = 14695981039346656037ULL;
    for (const unsigned char character : value)
    {
        hash ^= character;
        hash *= 1099511628211ULL;
    }
    return hash;
}
} // namespace

const char* toString(AdvertisedState state) noexcept
{
    switch (state)
    {
    case AdvertisedState::ready: return "ready";
    case AdvertisedState::draining: return "draining";
    }
    return "unknown";
}

const char* toString(InstanceState state) noexcept
{
    switch (state)
    {
    case InstanceState::ready: return "ready";
    case InstanceState::draining: return "draining";
    case InstanceState::expired: return "expired";
    }
    return "unknown";
}

const char* toString(ObservationStatus status) noexcept
{
    switch (status)
    {
    case ObservationStatus::accepted: return "accepted";
    case ObservationStatus::duplicate: return "duplicate";
    case ObservationStatus::staleIncarnation: return "stale-incarnation";
    case ObservationStatus::staleRevision: return "stale-revision";
    case ObservationStatus::identityConflict: return "identity-conflict";
    case ObservationStatus::invalid: return "invalid";
    case ObservationStatus::capacityExceeded: return "capacity-exceeded";
    }
    return "unknown";
}

const char* toString(RoutingPolicy policy) noexcept
{
    switch (policy)
    {
    case RoutingPolicy::roundRobin: return "round-robin";
    case RoutingPolicy::rendezvousHash: return "rendezvous-hash";
    case RoutingPolicy::preferLocal: return "prefer-local";
    }
    return "unknown";
}

const char* toString(SelectionStatus status) noexcept
{
    switch (status)
    {
    case SelectionStatus::selected: return "selected";
    case SelectionStatus::invalid: return "invalid";
    case SelectionStatus::noInstances: return "no-instances";
    case SelectionStatus::noReadyInstances: return "no-ready-instances";
    case SelectionStatus::noMatchingTags: return "no-matching-tags";
    case SelectionStatus::noEligibleMembers: return "no-eligible-members";
    case SelectionStatus::routingKeyRequired: return "routing-key-required";
    }
    return "unknown";
}

class Directory::Impl
{
public:
    struct Entry
    {
        Advertisement advertisement;
        TimePoint lastSeen;
        InstanceState state{InstanceState::ready};
    };

    Impl(Options value, Clock source)
        : options(value), clock(std::move(source))
    {
        if (options.advertisementTtl < std::chrono::milliseconds{100} ||
            options.advertisementTtl > std::chrono::hours{1})
            throw Poco::InvalidArgumentException(
                "Service Directory TTL must contain 100..3600000 milliseconds");
        if (options.tombstoneRetention < std::chrono::milliseconds{0} ||
            options.tombstoneRetention > std::chrono::hours{24})
            throw Poco::InvalidArgumentException(
                "Service Directory tombstone retention must contain 0..86400000 milliseconds");
        if (options.maximumInstances == 0 || options.maximumInstances > 100000)
            throw Poco::InvalidArgumentException(
                "Service Directory maximum instances must contain 1..100000");
        if (options.maximumInstancesPerService == 0 ||
            options.maximumInstancesPerService > options.maximumInstances)
            throw Poco::InvalidArgumentException(
                "Per-service capacity must be positive and not exceed total capacity");
        if (!clock) clock = [] { return std::chrono::steady_clock::now(); };
    }

    void refresh(TimePoint now) const
    {
        for (auto& [key, entry] : entries)
        {
            (void) key;
            if (entry.state != InstanceState::expired &&
                age(now, entry.lastSeen) >= options.advertisementTtl)
            {
                entry.state = InstanceState::expired;
                ++statistics.expiredTransitions;
                ++generation;
            }
        }
        for (auto iterator = entries.begin(); iterator != entries.end();)
        {
            if (iterator->second.state == InstanceState::expired &&
                age(now, iterator->second.lastSeen) >=
                    options.advertisementTtl + options.tombstoneRetention)
            {
                iterator = entries.erase(iterator);
                ++statistics.removed;
                ++generation;
            }
            else ++iterator;
        }
    }

    std::size_t serviceSize(const std::string& serviceName) const
    {
        return static_cast<std::size_t>(std::count_if(
            entries.begin(), entries.end(), [&](const auto& item) {
                return item.first.first == serviceName;
            }));
    }

    bool evictExpired(const std::optional<std::string>& serviceName)
    {
        auto selected = entries.end();
        for (auto iterator = entries.begin(); iterator != entries.end(); ++iterator)
        {
            if (iterator->second.state != InstanceState::expired) continue;
            if (serviceName && iterator->first.first != *serviceName) continue;
            if (selected == entries.end() ||
                iterator->second.lastSeen < selected->second.lastSeen)
                selected = iterator;
        }
        if (selected == entries.end()) return false;
        entries.erase(selected);
        ++statistics.removed;
        ++generation;
        return true;
    }

    Options options;
    Clock clock;
    mutable std::mutex mutex;
    mutable std::map<Key, Entry> entries;
    mutable Statistics statistics;
    mutable std::uint64_t generation{0};
};

Directory::Directory(Options options, Clock clock)
    : _impl(std::make_unique<Impl>(options, std::move(clock)))
{
}

Directory::~Directory() = default;

ObservationResult Directory::observe(Advertisement advertisement)
{
    const auto issue = validate(advertisement);
    std::lock_guard<std::mutex> lock(_impl->mutex);
    if (!issue.empty())
    {
        ++_impl->statistics.invalidRejected;
        return {ObservationStatus::invalid, false, _impl->generation, issue};
    }
    const auto now = _impl->clock();
    _impl->refresh(now);
    const Key key{advertisement.serviceName, advertisement.instanceId};
    auto iterator = _impl->entries.find(key);
    if (iterator != _impl->entries.end())
    {
        const auto& current = iterator->second.advertisement;
        if (current.runtimeId != advertisement.runtimeId)
        {
            ++_impl->statistics.identityConflicts;
            return {ObservationStatus::identityConflict, false, _impl->generation,
                    "service instance ID is already owned by another Runtime"};
        }
        if (advertisement.runtimeIncarnation < current.runtimeIncarnation)
        {
            ++_impl->statistics.staleRejected;
            return {ObservationStatus::staleIncarnation, false, _impl->generation,
                    "advertisement belongs to an older Runtime incarnation"};
        }
        if (advertisement.runtimeIncarnation == current.runtimeIncarnation)
        {
            if (advertisement.revision < current.revision)
            {
                ++_impl->statistics.staleRejected;
                return {ObservationStatus::staleRevision, false, _impl->generation,
                        "advertisement revision moved backwards"};
            }
            if (advertisement.revision == current.revision)
            {
                ++_impl->statistics.duplicates;
                return {ObservationStatus::duplicate, false, _impl->generation,
                        "duplicate advertisement did not extend instance TTL"};
            }
        }
        const auto state = instanceState(advertisement);
        iterator->second = {std::move(advertisement), now, state};
    }
    else
    {
        if (_impl->serviceSize(advertisement.serviceName) >=
                _impl->options.maximumInstancesPerService &&
            !_impl->evictExpired(advertisement.serviceName))
        {
            ++_impl->statistics.capacityRejected;
            return {ObservationStatus::capacityExceeded, false, _impl->generation,
                    "per-service capacity contains only active instances"};
        }
        if (_impl->entries.size() >= _impl->options.maximumInstances &&
            !_impl->evictExpired(std::nullopt))
        {
            ++_impl->statistics.capacityRejected;
            return {ObservationStatus::capacityExceeded, false, _impl->generation,
                    "directory capacity contains only active instances"};
        }
        const auto state = instanceState(advertisement);
        _impl->entries.emplace(
            key, Impl::Entry{std::move(advertisement), now, state});
    }
    ++_impl->statistics.accepted;
    ++_impl->generation;
    return {ObservationStatus::accepted, true, _impl->generation,
            "service advertisement accepted"};
}

bool Directory::withdraw(const std::string& serviceName,
                         const std::string& instanceId,
                         const std::string& runtimeId,
                         std::uint64_t runtimeIncarnation,
                         std::uint64_t finalRevision)
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    const auto now = _impl->clock();
    _impl->refresh(now);
    const auto iterator = _impl->entries.find({serviceName, instanceId});
    if (iterator == _impl->entries.end()) return false;
    auto& current = iterator->second;
    if (current.advertisement.runtimeId != runtimeId ||
        current.advertisement.runtimeIncarnation != runtimeIncarnation ||
        finalRevision <= current.advertisement.revision)
        return false;
    current.advertisement.revision = finalRevision;
    current.state = InstanceState::expired;
    current.lastSeen = now - _impl->options.advertisementTtl;
    ++_impl->statistics.withdrawals;
    ++_impl->generation;
    return true;
}

void Directory::sweep()
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    _impl->refresh(_impl->clock());
}

Snapshot Directory::snapshot() const
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    const auto now = _impl->clock();
    _impl->refresh(now);
    Snapshot result;
    result.generation = _impl->generation;
    result.statistics = _impl->statistics;
    result.instances.reserve(_impl->entries.size());
    std::set<std::string> services;
    for (const auto& [key, entry] : _impl->entries)
    {
        services.insert(key.first);
        result.instances.push_back(
            {entry.advertisement, entry.state, age(now, entry.lastSeen)});
        if (entry.state == InstanceState::ready) ++result.ready;
        else if (entry.state == InstanceState::draining) ++result.draining;
        else ++result.expired;
    }
    result.serviceCount = services.size();
    return result;
}

class Router::Impl
{
public:
    std::mutex mutex;
    std::map<std::string, std::uint64_t> cursors;
};

Router::Router() : _impl(std::make_unique<Impl>()) {}
Router::~Router() = default;

RouteResult Router::select(const Snapshot& snapshot,
                           const RouteRequest& request,
                           Eligibility eligibility)
{
    const auto issue = validate(request);
    if (!issue.empty())
        return {SelectionStatus::invalid, std::nullopt, 0, issue};
    if (request.policy == RoutingPolicy::rendezvousHash &&
        request.routingKey.empty())
        return {SelectionStatus::routingKeyRequired, std::nullopt, 0,
                "rendezvous-hash requires a non-empty routingKey"};

    std::vector<const InstanceSnapshot*> service;
    std::vector<const InstanceSnapshot*> ready;
    std::vector<const InstanceSnapshot*> tagged;
    std::vector<const InstanceSnapshot*> eligible;
    for (const auto& instance : snapshot.instances)
    {
        if (instance.advertisement.serviceName != request.serviceName) continue;
        service.push_back(&instance);
        if (instance.state != InstanceState::ready) continue;
        ready.push_back(&instance);
        if (!std::includes(instance.advertisement.tags.begin(),
                           instance.advertisement.tags.end(),
                           request.requiredTags.begin(), request.requiredTags.end()))
            continue;
        tagged.push_back(&instance);
        const InstanceIdentity identity{
            instance.advertisement.instanceId,
            instance.advertisement.runtimeId,
            instance.advertisement.runtimeIncarnation};
        if (!std::binary_search(request.excludedInstances.begin(),
                                request.excludedInstances.end(), identity) &&
            (!eligibility || eligibility(instance.advertisement)))
            eligible.push_back(&instance);
    }
    if (service.empty())
        return {SelectionStatus::noInstances, std::nullopt, 0,
                "service has no observed instances"};
    if (ready.empty())
        return {SelectionStatus::noReadyInstances, std::nullopt, 0,
                "service has no ready instances"};
    if (tagged.empty())
        return {SelectionStatus::noMatchingTags, std::nullopt, 0,
                "ready instances do not satisfy requiredTags"};
    if (eligible.empty())
        return {SelectionStatus::noEligibleMembers, std::nullopt, 0,
                "matching instances are excluded or not hosted by eligible Runtime members"};

    if (request.policy == RoutingPolicy::preferLocal &&
        !request.localRuntimeId.empty())
    {
        std::vector<const InstanceSnapshot*> local;
        std::copy_if(eligible.begin(), eligible.end(), std::back_inserter(local),
                     [&](const auto* item) {
                         return item->advertisement.runtimeId == request.localRuntimeId;
                     });
        if (!local.empty()) eligible = std::move(local);
    }

    const InstanceSnapshot* selected = nullptr;
    if (request.policy == RoutingPolicy::rendezvousHash)
    {
        std::uint64_t best = 0;
        for (const auto* item : eligible)
        {
            const auto score = fnv1a(
                request.serviceName + "\n" + request.routingKey + "\n" +
                item->advertisement.runtimeId + "\n" +
                std::to_string(item->advertisement.runtimeIncarnation) + "\n" +
                item->advertisement.instanceId);
            if (!selected || score > best)
            {
                best = score;
                selected = item;
            }
        }
    }
    else
    {
        std::lock_guard<std::mutex> lock(_impl->mutex);
        auto& cursor = _impl->cursors[request.serviceName];
        selected = eligible[static_cast<std::size_t>(cursor % eligible.size())];
        ++cursor;
    }
    return {SelectionStatus::selected, *selected, eligible.size(),
            "service instance selected"};
}
} // namespace PocoDDS::ServiceDirectory
