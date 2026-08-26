#include "PocoDDS/Membership/Membership.h"

#include <Poco/Exception.h>

#include <algorithm>
#include <limits>
#include <map>
#include <mutex>
#include <utility>

namespace PocoDDS::Membership
{
namespace
{
using TimePoint = std::chrono::steady_clock::time_point;

bool safeText(const std::string& value, std::size_t maximum, bool required)
{
    if ((required && value.empty()) || value.size() > maximum) return false;
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return character >= 0x21 && character <= 0x7e;
    });
}

std::string validate(const Heartbeat& heartbeat)
{
    if (!safeText(heartbeat.instanceId, 128, true))
        return "instanceId must contain 1..128 visible ASCII characters";
    if (heartbeat.incarnation == 0)
        return "incarnation must be greater than zero";
    if (heartbeat.sequence == 0)
        return "sequence must be greater than zero";
    if (!safeText(heartbeat.role, 64, false))
        return "role must contain at most 64 visible ASCII characters";
    if (!safeText(heartbeat.endpoint, 512, false))
        return "endpoint must contain at most 512 visible ASCII characters";
    if (heartbeat.capabilities.size() > 128)
        return "capability count exceeds 128";
    for (const auto& capability : heartbeat.capabilities)
        if (!safeText(capability, 128, true))
            return "capability must contain 1..128 visible ASCII characters";
    if (!std::is_sorted(heartbeat.capabilities.begin(), heartbeat.capabilities.end()) ||
        std::adjacent_find(heartbeat.capabilities.begin(), heartbeat.capabilities.end()) !=
            heartbeat.capabilities.end())
        return "capabilities must be sorted and unique";
    return {};
}

std::chrono::milliseconds age(TimePoint now, TimePoint lastSeen)
{
    if (now <= lastSeen) return std::chrono::milliseconds{0};
    return std::chrono::duration_cast<std::chrono::milliseconds>(now - lastSeen);
}
} // namespace

const char* toString(MemberState state) noexcept
{
    switch (state)
    {
    case MemberState::alive: return "alive";
    case MemberState::expired: return "expired";
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
    case ObservationStatus::staleSequence: return "stale-sequence";
    case ObservationStatus::invalid: return "invalid";
    case ObservationStatus::capacityExceeded: return "capacity-exceeded";
    }
    return "unknown";
}

class Registry::Impl
{
public:
    struct Entry
    {
        Heartbeat heartbeat;
        TimePoint lastSeen;
        MemberState state{MemberState::alive};
    };

    Impl(Options value, Clock source)
        : options(value), clock(std::move(source))
    {
        if (options.heartbeatTtl < std::chrono::milliseconds{100} ||
            options.heartbeatTtl > std::chrono::hours{1})
            throw Poco::InvalidArgumentException(
                "Membership heartbeat TTL must contain 100..3600000 milliseconds");
        if (options.tombstoneRetention < std::chrono::milliseconds{0} ||
            options.tombstoneRetention > std::chrono::hours{24})
            throw Poco::InvalidArgumentException(
                "Membership tombstone retention must contain 0..86400000 milliseconds");
        if (options.maximumMembers == 0 || options.maximumMembers > 100000)
            throw Poco::InvalidArgumentException(
                "Membership maximum members must contain 1..100000 entries");
        if (!clock) clock = [] { return std::chrono::steady_clock::now(); };
    }

    void refresh(TimePoint now) const
    {
        for (auto& [id, entry] : entries)
        {
            (void) id;
            if (entry.state == MemberState::alive &&
                age(now, entry.lastSeen) >= options.heartbeatTtl)
            {
                entry.state = MemberState::expired;
                ++statistics.expiredTransitions;
                ++generation;
            }
        }
        for (auto iterator = entries.begin(); iterator != entries.end();)
        {
            if (iterator->second.state == MemberState::expired &&
                age(now, iterator->second.lastSeen) >=
                    options.heartbeatTtl + options.tombstoneRetention)
            {
                iterator = entries.erase(iterator);
                ++statistics.removed;
                ++generation;
            }
            else ++iterator;
        }
    }

    bool evictOldestExpired()
    {
        auto selected = entries.end();
        for (auto iterator = entries.begin(); iterator != entries.end(); ++iterator)
            if (iterator->second.state == MemberState::expired &&
                (selected == entries.end() ||
                 iterator->second.lastSeen < selected->second.lastSeen))
                selected = iterator;
        if (selected == entries.end()) return false;
        entries.erase(selected);
        ++statistics.removed;
        ++generation;
        return true;
    }

    Options options;
    Clock clock;
    mutable std::mutex mutex;
    mutable std::map<std::string, Entry> entries;
    mutable Statistics statistics;
    mutable std::uint64_t generation{0};
};

Registry::Registry(Options options, Clock clock)
    : _impl(std::make_unique<Impl>(options, std::move(clock)))
{
}

Registry::~Registry() = default;

ObservationResult Registry::observe(Heartbeat heartbeat)
{
    const auto issue = validate(heartbeat);
    std::lock_guard<std::mutex> lock(_impl->mutex);
    if (!issue.empty())
    {
        ++_impl->statistics.invalidRejected;
        return {ObservationStatus::invalid, false, _impl->generation, issue};
    }

    const auto now = _impl->clock();
    _impl->refresh(now);
    auto iterator = _impl->entries.find(heartbeat.instanceId);
    if (iterator != _impl->entries.end())
    {
        const auto& current = iterator->second.heartbeat;
        if (heartbeat.incarnation < current.incarnation)
        {
            ++_impl->statistics.staleRejected;
            return {ObservationStatus::staleIncarnation, false, _impl->generation,
                    "heartbeat belongs to an older incarnation"};
        }
        if (heartbeat.incarnation == current.incarnation)
        {
            if (heartbeat.sequence < current.sequence)
            {
                ++_impl->statistics.staleRejected;
                return {ObservationStatus::staleSequence, false, _impl->generation,
                        "heartbeat sequence moved backwards"};
            }
            if (heartbeat.sequence == current.sequence)
            {
                ++_impl->statistics.duplicates;
                return {ObservationStatus::duplicate, false, _impl->generation,
                        "duplicate heartbeat did not extend member TTL"};
            }
        }
        iterator->second = {std::move(heartbeat), now, MemberState::alive};
    }
    else
    {
        if (_impl->entries.size() >= _impl->options.maximumMembers &&
            !_impl->evictOldestExpired())
        {
            ++_impl->statistics.capacityRejected;
            return {ObservationStatus::capacityExceeded, false, _impl->generation,
                    "membership capacity contains only live members"};
        }
        const auto instanceId = heartbeat.instanceId;
        _impl->entries.emplace(
            instanceId, Impl::Entry{std::move(heartbeat), now, MemberState::alive});
    }
    ++_impl->statistics.accepted;
    ++_impl->generation;
    return {ObservationStatus::accepted, true, _impl->generation, "heartbeat accepted"};
}

bool Registry::leave(const std::string& instanceId, std::uint64_t incarnation,
                     std::uint64_t finalSequence)
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    const auto now = _impl->clock();
    _impl->refresh(now);
    const auto iterator = _impl->entries.find(instanceId);
    if (iterator == _impl->entries.end() ||
        iterator->second.heartbeat.incarnation != incarnation ||
        finalSequence <= iterator->second.heartbeat.sequence)
        return false;
    iterator->second.heartbeat.sequence = finalSequence;
    iterator->second.state = MemberState::expired;
    iterator->second.lastSeen = now - _impl->options.heartbeatTtl;
    ++_impl->statistics.gracefulLeaves;
    ++_impl->generation;
    return true;
}

void Registry::sweep()
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    _impl->refresh(_impl->clock());
}

Snapshot Registry::snapshot() const
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    const auto now = _impl->clock();
    _impl->refresh(now);
    Snapshot result;
    result.generation = _impl->generation;
    result.statistics = _impl->statistics;
    result.members.reserve(_impl->entries.size());
    for (const auto& [id, entry] : _impl->entries)
    {
        (void) id;
        result.members.push_back({entry.heartbeat, entry.state, age(now, entry.lastSeen)});
        if (entry.state == MemberState::alive) ++result.alive;
        else ++result.expired;
    }
    return result;
}
} // namespace PocoDDS::Membership
