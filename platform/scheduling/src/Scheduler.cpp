#include "PocoDDS/Scheduling/Scheduler.h"

#include <algorithm>
#include <condition_variable>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <unordered_map>
#include <utility>

namespace PocoDDS::Scheduling
{
namespace
{
using Clock = std::chrono::steady_clock;
constexpr auto MAX_INTERVAL = std::chrono::hours(24);

std::uint64_t seedFor(const std::string& value) noexcept
{
    std::uint64_t result = 1469598103934665603ULL;
    for (const unsigned char character : value)
    {
        result ^= character;
        result *= 1099511628211ULL;
    }
    return result;
}

std::string validationError(const TaskSpec& spec)
{
    if (spec.id.empty() || spec.id.size() > 128)
        return "task id must contain between 1 and 128 characters";
    if (spec.owner.empty() || spec.owner.size() > 128)
        return "task owner must contain between 1 and 128 characters";
    if (spec.initialDelay.count() < 0 || spec.initialDelay > MAX_INTERVAL)
        return "initial delay must be between 0 and 86400000 milliseconds";
    if (spec.interval.count() <= 0 || spec.interval > MAX_INTERVAL)
        return "interval must be between 1 and 86400000 milliseconds";
    if (spec.jitter.count() < 0 || spec.jitter > spec.interval)
        return "jitter must be between 0 and the task interval";
    if (spec.rejectionBackoff.count() <= 0 ||
        spec.rejectionBackoff > std::chrono::hours(1))
        return "rejection backoff must be between 1 and 3600000 milliseconds";
    return {};
}
} // namespace

const char* toString(ScheduleMode value) noexcept
{
    switch (value)
    {
    case ScheduleMode::fixedDelay: return "fixed-delay";
    case ScheduleMode::fixedRate: return "fixed-rate";
    }
    return "fixed-delay";
}

const char* toString(MisfirePolicy value) noexcept
{
    switch (value)
    {
    case MisfirePolicy::skip: return "skip";
    case MisfirePolicy::coalesce: return "coalesce";
    }
    return "skip";
}

const char* toString(RegistrationStatus value) noexcept
{
    switch (value)
    {
    case RegistrationStatus::registered: return "registered";
    case RegistrationStatus::duplicate: return "duplicate";
    case RegistrationStatus::invalid: return "invalid";
    case RegistrationStatus::shuttingDown: return "shutting-down";
    }
    return "invalid";
}

const char* toString(ReconfigurationStatus value) noexcept
{
    switch (value)
    {
    case ReconfigurationStatus::reconfigured: return "reconfigured";
    case ReconfigurationStatus::notFound: return "not-found";
    case ReconfigurationStatus::invalid: return "invalid";
    case ReconfigurationStatus::shuttingDown: return "shutting-down";
    }
    return "invalid";
}

std::string validateTaskSpec(const TaskSpec& spec)
{
    return validationError(spec);
}

CancellationToken::CancellationToken(
    ResourceGovernance::CancellationToken governance,
    std::shared_ptr<std::atomic<bool>> scheduleCancellation)
    : _governance(std::move(governance)),
      _scheduleCancellation(std::move(scheduleCancellation))
{
}

bool CancellationToken::requested() const noexcept
{
    return _governance.requested() ||
        (_scheduleCancellation &&
         _scheduleCancellation->load(std::memory_order_acquire));
}

struct Scheduler::Impl
{
    struct Task
    {
        TaskSpec spec;
        TaskCallback run;
        CompletionCallback complete;
        Clock::time_point nextDue{};
        std::shared_ptr<std::atomic<bool>> cancellation;
        bool cancelled{false};
        bool inFlight{false};
        bool dispatching{false};
        bool coalesced{false};
        std::uint64_t jitterState{0};
        std::uint64_t sequence{0};
        std::uint64_t triggered{0};
        std::uint64_t accepted{0};
        std::uint64_t rejected{0};
        std::uint64_t misfires{0};
        std::uint64_t completed{0};
        std::uint64_t failed{0};
        std::optional<ResourceGovernance::CompletionStatus> lastStatus;
        std::string lastMessage;
    };

    struct Invocation
    {
        std::shared_ptr<Task> task;
        std::shared_ptr<std::atomic<bool>> cancellation;
    };

    explicit Impl(SubmitFunction value): submit(std::move(value))
    {
        if (!submit) throw std::invalid_argument("scheduler submit function is required");
        timer = std::thread([this] { timerLoop(); });
    }

    ~Impl() { shutdown(); }

    std::chrono::milliseconds nextJitter(Task& task) noexcept
    {
        if (task.spec.jitter.count() == 0) return std::chrono::milliseconds{0};
        task.jitterState = task.jitterState * 6364136223846793005ULL +
            1442695040888963407ULL;
        const auto range = static_cast<std::uint64_t>(task.spec.jitter.count()) + 1;
        return std::chrono::milliseconds(task.jitterState % range);
    }

    void advanceFixedRate(Task& task)
    {
        task.nextDue += task.spec.interval + nextJitter(task);
    }

    std::shared_ptr<Task> earliestTask() const
    {
        std::shared_ptr<Task> selected;
        for (const auto& entry : tasks)
        {
            const auto& task = entry.second;
            if (task->cancelled || task->dispatching) continue;
            if (!task->spec.enabled) continue;
            if (task->inFlight && task->spec.mode == ScheduleMode::fixedDelay) continue;
            if (!selected || task->nextDue < selected->nextDue) selected = task;
        }
        return selected;
    }

    void completeInvocation(const std::shared_ptr<Invocation>& invocation,
                            const ResourceGovernance::Completion& completion) noexcept
    {
        auto task = std::move(invocation->task);
        if (!task) return;

        bool invokeUser = false;
        {
            std::lock_guard<std::mutex> lock(mutex);
            invokeUser = !task->cancelled;
        }
        if (invokeUser && task->complete)
        {
            try { task->complete(completion); }
            catch (...) {}
        }

        {
            std::lock_guard<std::mutex> lock(mutex);
            ++task->completed;
            task->lastStatus = completion.status;
            task->lastMessage = completion.message;
            if (completion.status != ResourceGovernance::CompletionStatus::succeeded)
                ++task->failed;
            // Publish the idle state only after Bundle-owned callback targets have
            // been destroyed. cancelAndWait() is allowed to wake spuriously, so
            // the predicate itself must imply that no unload-sensitive callback
            // remains retained by the scheduler.
            if (task->cancelled || stopping)
            {
                task->run = {};
                task->complete = {};
            }
            task->inFlight = false;
            if (!task->cancelled && !stopping && task->spec.enabled)
            {
                const auto now = Clock::now();
                if (task->coalesced)
                {
                    task->coalesced = false;
                    task->nextDue = now;
                }
                else if (task->spec.mode == ScheduleMode::fixedDelay)
                {
                    task->nextDue = now + task->spec.interval + nextJitter(*task);
                }
            }
        }
        // ResourceGovernor retains only Invocation after this point, never Bundle callbacks.
        task.reset();
        changed.notify_all();
    }

    void timerLoop() noexcept
    {
        std::unique_lock<std::mutex> lock(mutex);
        while (!stopping)
        {
            auto task = earliestTask();
            if (!task)
            {
                changed.wait(lock, [&] { return stopping || earliestTask() != nullptr; });
                continue;
            }
            const auto now = Clock::now();
            if (task->nextDue > now)
            {
                const auto due = task->nextDue;
                // Never retain Bundle callbacks while the timer releases the lock.
                // cancelAndWait() can now erase and destroy an idle future task fully.
                task.reset();
                changed.wait_until(lock, due);
                continue;
            }

            if (task->inFlight)
            {
                do
                {
                    ++task->misfires;
                    if (task->spec.misfire == MisfirePolicy::coalesce)
                        task->coalesced = true;
                    advanceFixedRate(*task);
                }
                while (task->nextDue <= Clock::now());
                continue;
            }

            task->inFlight = true;
            task->dispatching = true;
            task->cancellation = std::make_shared<std::atomic<bool>>(false);
            ++task->sequence;
            ++task->triggered;
            if (task->spec.mode == ScheduleMode::fixedRate)
                advanceFixedRate(*task);
            else
                task->nextDue = Clock::time_point::max();

            auto invocation = std::make_shared<Invocation>();
            invocation->task = task;
            invocation->cancellation = task->cancellation;
            const auto workId = task->spec.id + "#" + std::to_string(task->sequence);
            const auto owner = task->spec.owner;
            ResourceGovernance::WorkItem work{
                workId,
                [invocation](const ResourceGovernance::CancellationToken& governance) {
                    const auto current = invocation->task;
                    if (!current || invocation->cancellation->load(std::memory_order_acquire))
                        return;
                    current->run(CancellationToken(governance, invocation->cancellation));
                },
                [this, invocation](const ResourceGovernance::Completion& completion) {
                    completeInvocation(invocation, completion);
                }};

            lock.unlock();
            ResourceGovernance::Admission admission;
            try
            {
                admission = submit(owner, std::move(work));
            }
            catch (const std::exception& exception)
            {
                admission = {ResourceGovernance::AdmissionStatus::invalid, owner, workId,
                             exception.what()};
            }
            catch (...)
            {
                admission = {ResourceGovernance::AdmissionStatus::invalid, owner, workId,
                             "scheduler submit function threw a non-standard exception"};
            }
            lock.lock();

            task->dispatching = false;
            if (admission.status == ResourceGovernance::AdmissionStatus::accepted)
            {
                ++task->accepted;
            }
            else if (task->inFlight)
            {
                ++task->rejected;
                task->lastMessage = admission.message;
                task->inFlight = false;
                invocation->task.reset();
                if (!task->cancelled && !stopping)
                {
                    const auto retry = Clock::now() + task->spec.rejectionBackoff;
                    if (task->spec.mode == ScheduleMode::fixedDelay || retry < task->nextDue)
                        task->nextDue = retry;
                }
            }
            invocation.reset();
            task.reset();
            changed.notify_all();
        }
    }

    Registration schedule(TaskSpec spec, TaskCallback run,
                          CompletionCallback complete)
    {
        auto error = validationError(spec);
        if (error.empty() && !run) error = "task callback is required";
        if (!error.empty()) return {RegistrationStatus::invalid, spec.id, error};
        std::lock_guard<std::mutex> lock(mutex);
        if (stopping)
            return {RegistrationStatus::shuttingDown, spec.id,
                    "scheduler is shutting down"};
        if (tasks.find(spec.id) != tasks.end())
            return {RegistrationStatus::duplicate, spec.id,
                    "scheduled task id already exists"};
        auto task = std::make_shared<Task>();
        task->spec = std::move(spec);
        task->run = std::move(run);
        task->complete = std::move(complete);
        task->jitterState = seedFor(task->spec.id);
        task->nextDue = task->spec.enabled
            ? Clock::now() + task->spec.initialDelay
            : Clock::time_point::max();
        const auto id = task->spec.id;
        tasks.emplace(id, std::move(task));
        changed.notify_all();
        return {RegistrationStatus::registered, id, "registered"};
    }

    Reconfiguration reconfigure(TaskSpec spec)
    {
        const auto error = validationError(spec);
        if (!error.empty())
            return {ReconfigurationStatus::invalid, spec.id, error};
        std::lock_guard<std::mutex> lock(mutex);
        if (stopping)
            return {ReconfigurationStatus::shuttingDown, spec.id,
                    "scheduler is shutting down"};
        const auto found = tasks.find(spec.id);
        if (found == tasks.end())
            return {ReconfigurationStatus::notFound, spec.id,
                    "scheduled task id was not found"};
        auto& task = *found->second;
        if (spec.owner != task.spec.owner)
            return {ReconfigurationStatus::invalid, spec.id,
                    "scheduled task owner cannot be changed"};

        task.spec = std::move(spec);
        task.coalesced = false;
        task.jitterState = seedFor(task.spec.id) ^ task.sequence;
        task.nextDue = task.spec.enabled
            ? Clock::now() + task.spec.initialDelay
            : Clock::time_point::max();
        changed.notify_all();
        return {ReconfigurationStatus::reconfigured, task.spec.id, "reconfigured"};
    }

    bool cancelAndWait(const std::string& taskId) noexcept
    {
        std::shared_ptr<Task> task;
        {
            std::unique_lock<std::mutex> lock(mutex);
            const auto found = tasks.find(taskId);
            if (found == tasks.end()) return false;
            task = found->second;
            task->cancelled = true;
            task->nextDue = Clock::time_point::max();
            if (task->cancellation)
                task->cancellation->store(true, std::memory_order_release);
            changed.notify_all();
            changed.wait(lock, [&] { return !task->inFlight && !task->dispatching; });
            tasks.erase(taskId);
        }
        // Destroy Bundle-owned std::function targets before returning to its activator.
        task.reset();
        return true;
    }

    TaskSnapshot snapshotOf(const std::shared_ptr<Task>& task) const
    {
        std::optional<std::chrono::milliseconds> next;
        if (!task->cancelled && task->nextDue != Clock::time_point::max())
        {
            const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
                task->nextDue - Clock::now());
            next = std::max(remaining, std::chrono::milliseconds{0});
        }
        return {task->spec, task->inFlight, task->coalesced, next,
                task->triggered, task->accepted, task->rejected, task->misfires,
                task->completed, task->failed, task->lastStatus, task->lastMessage};
    }

    std::optional<TaskSnapshot> snapshot(const std::string& taskId) const
    {
        std::lock_guard<std::mutex> lock(mutex);
        const auto found = tasks.find(taskId);
        if (found == tasks.end()) return std::nullopt;
        return snapshotOf(found->second);
    }

    std::vector<TaskSnapshot> snapshots() const
    {
        std::lock_guard<std::mutex> lock(mutex);
        std::vector<TaskSnapshot> result;
        result.reserve(tasks.size());
        for (const auto& entry : tasks) result.push_back(snapshotOf(entry.second));
        std::sort(result.begin(), result.end(), [](const auto& left, const auto& right) {
            if (left.spec.owner != right.spec.owner)
                return left.spec.owner < right.spec.owner;
            return left.spec.id < right.spec.id;
        });
        return result;
    }

    void shutdown() noexcept
    {
        {
            std::lock_guard<std::mutex> lock(mutex);
            if (stopping) return;
            stopping = true;
            for (const auto& entry : tasks)
            {
                entry.second->cancelled = true;
                if (entry.second->cancellation)
                    entry.second->cancellation->store(true, std::memory_order_release);
            }
        }
        changed.notify_all();
        if (timer.joinable()) timer.join();
        std::unique_lock<std::mutex> lock(mutex);
        changed.wait(lock, [&] {
            return std::all_of(tasks.begin(), tasks.end(), [](const auto& entry) {
                return !entry.second->inFlight && !entry.second->dispatching;
            });
        });
        tasks.clear();
    }

    SubmitFunction submit;
    mutable std::mutex mutex;
    std::condition_variable changed;
    std::unordered_map<std::string, std::shared_ptr<Task>> tasks;
    std::thread timer;
    bool stopping{false};
};

Scheduler::Scheduler(SubmitFunction submit): _impl(std::make_unique<Impl>(std::move(submit))) {}
Scheduler::~Scheduler() = default;

Registration Scheduler::schedule(TaskSpec spec, TaskCallback run,
                                 CompletionCallback complete)
{
    return _impl->schedule(std::move(spec), std::move(run), std::move(complete));
}

Reconfiguration Scheduler::reconfigure(TaskSpec spec)
{
    return _impl->reconfigure(std::move(spec));
}

bool Scheduler::cancelAndWait(const std::string& taskId) noexcept
{
    return _impl->cancelAndWait(taskId);
}

std::optional<TaskSnapshot> Scheduler::snapshot(const std::string& taskId) const
{
    return _impl->snapshot(taskId);
}

std::vector<TaskSnapshot> Scheduler::snapshots() const
{
    return _impl->snapshots();
}

void Scheduler::shutdown() noexcept
{
    _impl->shutdown();
}
} // namespace PocoDDS::Scheduling
