#pragma once

#include "PocoDDS/Membership/Export.h"

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::Membership
{
enum class MemberState
{
    alive,
    expired
};

enum class ObservationStatus
{
    accepted,
    duplicate,
    staleIncarnation,
    staleSequence,
    invalid,
    capacityExceeded
};

PDR_MEMBERSHIP_API const char* toString(MemberState state) noexcept;
PDR_MEMBERSHIP_API const char* toString(ObservationStatus status) noexcept;

struct Options
{
    std::chrono::milliseconds heartbeatTtl{5000};
    std::chrono::milliseconds tombstoneRetention{30000};
    std::size_t maximumMembers{1024};
};

struct Heartbeat
{
    std::string instanceId;
    std::uint64_t incarnation{0};
    std::uint64_t sequence{0};
    std::string role;
    std::string endpoint;
    std::vector<std::string> capabilities;
};

struct ObservationResult
{
    ObservationStatus status{ObservationStatus::invalid};
    bool changed{false};
    std::uint64_t membershipGeneration{0};
    std::string detail;

    explicit operator bool() const noexcept
    {
        return status == ObservationStatus::accepted ||
               status == ObservationStatus::duplicate;
    }
};

struct MemberSnapshot
{
    Heartbeat heartbeat;
    MemberState state{MemberState::expired};
    std::chrono::milliseconds age{0};
};

struct Statistics
{
    std::uint64_t accepted{0};
    std::uint64_t duplicates{0};
    std::uint64_t staleRejected{0};
    std::uint64_t invalidRejected{0};
    std::uint64_t capacityRejected{0};
    std::uint64_t expiredTransitions{0};
    std::uint64_t gracefulLeaves{0};
    std::uint64_t removed{0};
};

struct Snapshot
{
    std::uint64_t generation{0};
    std::size_t alive{0};
    std::size_t expired{0};
    std::vector<MemberSnapshot> members;
    Statistics statistics;
};

class PDR_MEMBERSHIP_API Registry
{
public:
    using Clock = std::function<std::chrono::steady_clock::time_point()>;

    explicit Registry(Options options = {}, Clock clock = {});
    ~Registry();

    Registry(const Registry&) = delete;
    Registry& operator=(const Registry&) = delete;

    ObservationResult observe(Heartbeat heartbeat);

    /// Removes only the matching incarnation. A delayed leave from an old
    /// process therefore cannot remove its replacement.
    bool leave(const std::string& instanceId, std::uint64_t incarnation,
               std::uint64_t finalSequence);

    /// Applies TTL transitions and tombstone retention immediately.
    void sweep();

    [[nodiscard]] Snapshot snapshot() const;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Membership
