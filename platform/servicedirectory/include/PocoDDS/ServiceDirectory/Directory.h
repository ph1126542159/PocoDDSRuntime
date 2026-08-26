#pragma once

#include "PocoDDS/ServiceDirectory/Export.h"

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::ServiceDirectory
{
enum class AdvertisedState
{
    ready,
    draining
};

enum class InstanceState
{
    ready,
    draining,
    expired
};

enum class ObservationStatus
{
    accepted,
    duplicate,
    staleIncarnation,
    staleRevision,
    identityConflict,
    invalid,
    capacityExceeded
};

enum class RoutingPolicy
{
    roundRobin,
    rendezvousHash,
    preferLocal
};

enum class SelectionStatus
{
    selected,
    invalid,
    noInstances,
    noReadyInstances,
    noMatchingTags,
    noEligibleMembers,
    routingKeyRequired
};

PDR_SERVICE_DIRECTORY_API const char* toString(AdvertisedState state) noexcept;
PDR_SERVICE_DIRECTORY_API const char* toString(InstanceState state) noexcept;
PDR_SERVICE_DIRECTORY_API const char* toString(ObservationStatus status) noexcept;
PDR_SERVICE_DIRECTORY_API const char* toString(RoutingPolicy policy) noexcept;
PDR_SERVICE_DIRECTORY_API const char* toString(SelectionStatus status) noexcept;

struct Options
{
    std::chrono::milliseconds advertisementTtl{5000};
    std::chrono::milliseconds tombstoneRetention{30000};
    std::size_t maximumInstances{4096};
    std::size_t maximumInstancesPerService{256};
};

struct ServiceDescriptor
{
    std::string serviceName;
    std::string instanceId;
    std::string endpoint;
    std::string protocol;
    std::string zone;
    std::vector<std::string> tags;
    AdvertisedState state{AdvertisedState::ready};
};

struct Advertisement : ServiceDescriptor
{
    std::string runtimeId;
    std::uint64_t runtimeIncarnation{0};
    std::uint64_t revision{0};
};

struct ObservationResult
{
    ObservationStatus status{ObservationStatus::invalid};
    bool changed{false};
    std::uint64_t generation{0};
    std::string detail;

    explicit operator bool() const noexcept
    {
        return status == ObservationStatus::accepted ||
               status == ObservationStatus::duplicate;
    }
};

struct InstanceSnapshot
{
    Advertisement advertisement;
    InstanceState state{InstanceState::expired};
    std::chrono::milliseconds age{0};
};

struct Statistics
{
    std::uint64_t accepted{0};
    std::uint64_t duplicates{0};
    std::uint64_t staleRejected{0};
    std::uint64_t identityConflicts{0};
    std::uint64_t invalidRejected{0};
    std::uint64_t capacityRejected{0};
    std::uint64_t expiredTransitions{0};
    std::uint64_t withdrawals{0};
    std::uint64_t removed{0};
};

struct Snapshot
{
    std::uint64_t generation{0};
    std::size_t serviceCount{0};
    std::size_t ready{0};
    std::size_t draining{0};
    std::size_t expired{0};
    std::vector<InstanceSnapshot> instances;
    Statistics statistics;
};

struct InstanceIdentity
{
    std::string instanceId;
    std::string runtimeId;
    std::uint64_t runtimeIncarnation{0};

    bool operator==(const InstanceIdentity& other) const noexcept
    {
        return instanceId == other.instanceId && runtimeId == other.runtimeId &&
               runtimeIncarnation == other.runtimeIncarnation;
    }

    bool operator<(const InstanceIdentity& other) const noexcept
    {
        if (instanceId != other.instanceId) return instanceId < other.instanceId;
        if (runtimeId != other.runtimeId) return runtimeId < other.runtimeId;
        return runtimeIncarnation < other.runtimeIncarnation;
    }
};

class PDR_SERVICE_DIRECTORY_API Directory
{
public:
    using Clock = std::function<std::chrono::steady_clock::time_point()>;

    explicit Directory(Options options = {}, Clock clock = {});
    ~Directory();

    Directory(const Directory&) = delete;
    Directory& operator=(const Directory&) = delete;

    ObservationResult observe(Advertisement advertisement);
    bool withdraw(const std::string& serviceName,
                  const std::string& instanceId,
                  const std::string& runtimeId,
                  std::uint64_t runtimeIncarnation,
                  std::uint64_t finalRevision);
    void sweep();
    [[nodiscard]] Snapshot snapshot() const;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};

struct RouteRequest
{
    std::string serviceName;
    RoutingPolicy policy{RoutingPolicy::roundRobin};
    std::string routingKey;
    std::string localRuntimeId;
    std::vector<std::string> requiredTags;
    std::vector<InstanceIdentity> excludedInstances;
};

struct RouteResult
{
    SelectionStatus status{SelectionStatus::invalid};
    std::optional<InstanceSnapshot> instance;
    std::size_t candidates{0};
    std::string detail;

    explicit operator bool() const noexcept
    {
        return status == SelectionStatus::selected && instance.has_value();
    }
};

class PDR_SERVICE_DIRECTORY_API Router
{
public:
    using Eligibility = std::function<bool(const Advertisement&)>;

    Router();
    ~Router();

    Router(const Router&) = delete;
    Router& operator=(const Router&) = delete;

    RouteResult select(const Snapshot& snapshot,
                       const RouteRequest& request,
                       Eligibility eligibility = {});

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::ServiceDirectory
