#pragma once

#include "PocoDDS/ServiceClient/Export.h"

#include <PocoDDS/ServiceDirectory/Directory.h>

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::ServiceClient
{
enum class AttemptDisposition
{
    succeeded,
    retryableFailure,
    permanentFailure
};

enum class InvocationStatus
{
    succeeded,
    invalid,
    noRoute,
    circuitOpen,
    circuitCapacityExceeded,
    deadlineExceeded,
    cancelled,
    failed
};

enum class CircuitState
{
    closed,
    open,
    halfOpen
};

PDR_SERVICE_CLIENT_API const char* toString(AttemptDisposition value) noexcept;
PDR_SERVICE_CLIENT_API const char* toString(InvocationStatus value) noexcept;
PDR_SERVICE_CLIENT_API const char* toString(CircuitState value) noexcept;

struct Policy
{
    std::size_t maximumAttempts{3};
    std::chrono::milliseconds timeout{5000};
    std::chrono::milliseconds initialBackoff{50};
    std::chrono::milliseconds maximumBackoff{1000};
    double backoffMultiplier{2.0};
    std::size_t circuitFailureThreshold{3};
    std::chrono::milliseconds circuitResetTimeout{5000};
    std::size_t maximumCircuitEntries{4096};
    std::chrono::milliseconds circuitIdleRetention{600000};
};

struct InvocationRequest
{
    ServiceDirectory::RouteRequest route;
    std::string operation;
    bool idempotent{false};
    std::string idempotencyKey;
};

struct AttemptContext
{
    ServiceDirectory::InstanceSnapshot instance;
    std::size_t attempt{0};
    std::chrono::milliseconds remaining{0};
    std::string operation;
    std::string idempotencyKey;
};

struct PDR_SERVICE_CLIENT_API AttemptResult
{
    AttemptDisposition disposition{AttemptDisposition::permanentFailure};
    bool endpointHealthy{false};
    std::vector<std::uint8_t> payload;
    std::string code;
    std::string detail;

    static AttemptResult success(std::vector<std::uint8_t> payload = {});
    static AttemptResult retryable(std::string code, std::string detail);
    static AttemptResult permanent(std::string code, std::string detail,
                                   bool endpointHealthy = true);
};

struct AttemptRecord
{
    std::size_t attempt{0};
    std::string instanceId;
    std::string runtimeId;
    std::uint64_t runtimeIncarnation{0};
    AttemptDisposition disposition{AttemptDisposition::permanentFailure};
    std::string code;
};

struct InvocationResult
{
    InvocationStatus status{InvocationStatus::invalid};
    std::size_t attempts{0};
    std::optional<ServiceDirectory::InstanceSnapshot> instance;
    std::vector<std::uint8_t> payload;
    std::string code;
    std::string detail;
    std::vector<AttemptRecord> history;

    explicit operator bool() const noexcept
    {
        return status == InvocationStatus::succeeded;
    }
};

struct CircuitSnapshot
{
    std::string serviceName;
    std::string instanceId;
    std::string runtimeId;
    std::uint64_t runtimeIncarnation{0};
    CircuitState state{CircuitState::closed};
    std::size_t consecutiveFailures{0};
    bool probeInFlight{false};
};

struct Snapshot
{
    std::uint64_t calls{0};
    std::uint64_t succeeded{0};
    std::uint64_t failed{0};
    std::uint64_t attempts{0};
    std::uint64_t retries{0};
    std::uint64_t noRoute{0};
    std::uint64_t circuitRejected{0};
    std::uint64_t deadlineExceeded{0};
    std::uint64_t cancelled{0};
    std::vector<CircuitSnapshot> circuits;
};

class PDR_SERVICE_CLIENT_API Client
{
public:
    using Clock = std::function<std::chrono::steady_clock::time_point()>;
    using Sleeper = std::function<void(std::chrono::milliseconds)>;
    using Route = std::function<ServiceDirectory::RouteResult(
        const ServiceDirectory::RouteRequest&)>;
    using Invoke = std::function<AttemptResult(const AttemptContext&)>;
    using Cancelled = std::function<bool()>;

    Client(Policy policy, Route route, Clock clock = {}, Sleeper sleeper = {});
    ~Client();

    Client(const Client&) = delete;
    Client& operator=(const Client&) = delete;

    InvocationResult invoke(const InvocationRequest& request,
                            const Invoke& invoke,
                            const Cancelled& cancelled = {});
    [[nodiscard]] Snapshot snapshot() const;
    bool resetCircuit(const std::string& serviceName,
                      const std::string& instanceId);

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::ServiceClient
