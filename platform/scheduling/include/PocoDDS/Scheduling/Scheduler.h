#pragma once

#include "PocoDDS/Scheduling/Export.h"

#include "PocoDDS/ResourceGovernance/ResourceGovernor.h"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::Scheduling
{
enum class ScheduleMode
{
    fixedDelay,
    fixedRate
};

enum class MisfirePolicy
{
    skip,
    coalesce
};

enum class RegistrationStatus
{
    registered,
    duplicate,
    invalid,
    shuttingDown
};

enum class ReconfigurationStatus
{
    reconfigured,
    notFound,
    invalid,
    shuttingDown
};

PDR_SCHEDULING_API const char* toString(ScheduleMode value) noexcept;
PDR_SCHEDULING_API const char* toString(MisfirePolicy value) noexcept;
PDR_SCHEDULING_API const char* toString(RegistrationStatus value) noexcept;
PDR_SCHEDULING_API const char* toString(ReconfigurationStatus value) noexcept;

class PDR_SCHEDULING_API CancellationToken
{
public:
    CancellationToken(ResourceGovernance::CancellationToken governance,
                      std::shared_ptr<std::atomic<bool>> scheduleCancellation);
    [[nodiscard]] bool requested() const noexcept;

private:
    ResourceGovernance::CancellationToken _governance;
    std::shared_ptr<std::atomic<bool>> _scheduleCancellation;
};

struct TaskSpec
{
    std::string id;
    std::string owner;
    bool enabled{true};
    std::chrono::milliseconds initialDelay{0};
    std::chrono::milliseconds interval{1000};
    std::chrono::milliseconds jitter{0};
    std::chrono::milliseconds rejectionBackoff{100};
    ScheduleMode mode{ScheduleMode::fixedDelay};
    MisfirePolicy misfire{MisfirePolicy::skip};
};

struct Registration
{
    RegistrationStatus status{RegistrationStatus::invalid};
    std::string taskId;
    std::string message;
};

struct Reconfiguration
{
    ReconfigurationStatus status{ReconfigurationStatus::invalid};
    std::string taskId;
    std::string message;
};

PDR_SCHEDULING_API std::string validateTaskSpec(const TaskSpec& spec);

struct TaskSnapshot
{
    TaskSpec spec;
    bool inFlight{false};
    bool coalesced{false};
    std::optional<std::chrono::milliseconds> nextRunIn;
    std::uint64_t triggered{0};
    std::uint64_t accepted{0};
    std::uint64_t rejected{0};
    std::uint64_t misfires{0};
    std::uint64_t completed{0};
    std::uint64_t failed{0};
    std::optional<ResourceGovernance::CompletionStatus> lastStatus;
    std::string lastMessage;
};

using TaskCallback = std::function<void(const CancellationToken&)>;
using CompletionCallback =
    std::function<void(const ResourceGovernance::Completion&)>;

class PDR_SCHEDULING_API Scheduler
{
public:
    using SubmitFunction = std::function<ResourceGovernance::Admission(
        const std::string&, ResourceGovernance::WorkItem)>;

    explicit Scheduler(SubmitFunction submit);
    ~Scheduler();

    Scheduler(const Scheduler&) = delete;
    Scheduler& operator=(const Scheduler&) = delete;

    Registration schedule(TaskSpec spec, TaskCallback run,
                          CompletionCallback complete = {});
    Reconfiguration reconfigure(TaskSpec spec);
    bool cancelAndWait(const std::string& taskId) noexcept;
    [[nodiscard]] std::optional<TaskSnapshot> snapshot(
        const std::string& taskId) const;
    [[nodiscard]] std::vector<TaskSnapshot> snapshots() const;
    void shutdown() noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Scheduling
