#pragma once

#include "PocoDDS/ResourceGovernance/Export.h"

#include <atomic>
#include <chrono>
#include <cstddef>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::ResourceGovernance
{
enum class AdmissionStatus
{
    accepted,
    queueFull,
    circuitOpen,
    shuttingDown,
    invalid
};

enum class CompletionStatus
{
    succeeded,
    failed,
    queueTimedOut,
    executionTimedOut,
    circuitOpen,
    cancelled
};

enum class CircuitState
{
    closed,
    open,
    halfOpen
};

enum class ShutdownMode
{
    drain,
    cancelPending
};

PDR_RESOURCE_GOVERNANCE_API const char* toString(AdmissionStatus value) noexcept;
PDR_RESOURCE_GOVERNANCE_API const char* toString(CompletionStatus value) noexcept;
PDR_RESOURCE_GOVERNANCE_API const char* toString(CircuitState value) noexcept;

struct Policy
{
    std::string owner;
    std::size_t maximumConcurrency{2};
    std::size_t queueCapacity{128};
    std::chrono::milliseconds queueTimeout{1000};
    std::chrono::milliseconds executionTimeout{30000};
    std::size_t failureThreshold{5};
    std::chrono::milliseconds circuitResetTimeout{10000};
};

class CancellationToken
{
public:
    CancellationToken() = default;
    explicit CancellationToken(std::shared_ptr<std::atomic<bool>> requested);
    [[nodiscard]] bool requested() const noexcept;

private:
    std::shared_ptr<std::atomic<bool>> _requested;
};

struct Completion
{
    std::string owner;
    std::string workId;
    CompletionStatus status{CompletionStatus::failed};
    std::string message;
    std::chrono::microseconds queueDuration{0};
    std::chrono::microseconds executionDuration{0};
};

struct WorkItem
{
    std::string id;
    std::function<void(const CancellationToken&)> run;
    std::function<void(const Completion&)> complete;
};

struct Admission
{
    AdmissionStatus status{AdmissionStatus::invalid};
    std::string owner;
    std::string workId;
    std::string message;
};

struct Snapshot
{
    Policy policy;
    CircuitState circuit{CircuitState::closed};
    bool stopping{false};
    std::size_t active{0};
    std::size_t pending{0};
    std::size_t consecutiveFailures{0};
    std::uint64_t submitted{0};
    std::uint64_t accepted{0};
    std::uint64_t rejectedQueueFull{0};
    std::uint64_t rejectedCircuitOpen{0};
    std::uint64_t queueTimedOut{0};
    std::uint64_t executionTimedOut{0};
    std::uint64_t succeeded{0};
    std::uint64_t failed{0};
    std::uint64_t cancelled{0};
};

class PDR_RESOURCE_GOVERNANCE_API ResourceGovernor
{
public:
    explicit ResourceGovernor(Policy defaultPolicy,
                              std::vector<Policy> overrides = {});
    ~ResourceGovernor();

    ResourceGovernor(const ResourceGovernor&) = delete;
    ResourceGovernor& operator=(const ResourceGovernor&) = delete;

    Admission submit(const std::string& owner, WorkItem item);
    [[nodiscard]] Snapshot snapshot(const std::string& owner) const;
    [[nodiscard]] std::vector<Snapshot> snapshots() const;
    void shutdown(ShutdownMode mode = ShutdownMode::cancelPending) noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::ResourceGovernance
