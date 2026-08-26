#include "PocoDDS/ResourceGovernance/ResourceGovernor.h"

#include <algorithm>
#include <condition_variable>
#include <deque>
#include <map>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <unordered_map>
#include <utility>

namespace PocoDDS::ResourceGovernance
{
namespace
{
using Clock = std::chrono::steady_clock;

void validatePolicy(const Policy& policy, bool requireOwner)
{
    if (requireOwner && policy.owner.empty())
        throw std::invalid_argument("resource governance policy owner is required");
    if (policy.maximumConcurrency == 0 || policy.maximumConcurrency > 64)
        throw std::invalid_argument("maximumConcurrency must be between 1 and 64");
    if (policy.queueCapacity == 0 || policy.queueCapacity > 100000)
        throw std::invalid_argument("queueCapacity must be between 1 and 100000");
    if (policy.queueTimeout.count() <= 0 || policy.queueTimeout.count() > 3600000)
        throw std::invalid_argument("queueTimeout must be between 1 and 3600000 milliseconds");
    if (policy.executionTimeout.count() <= 0 || policy.executionTimeout.count() > 3600000)
        throw std::invalid_argument(
            "executionTimeout must be between 1 and 3600000 milliseconds");
    if (policy.failureThreshold == 0 || policy.failureThreshold > 100000)
        throw std::invalid_argument("failureThreshold must be between 1 and 100000");
    if (policy.circuitResetTimeout.count() <= 0 ||
        policy.circuitResetTimeout.count() > 3600000)
        throw std::invalid_argument(
            "circuitResetTimeout must be between 1 and 3600000 milliseconds");
}

void notify(const WorkItem& item, const Completion& completion) noexcept
{
    if (!item.complete) return;
    try { item.complete(completion); }
    catch (...) {}
}
} // namespace

const char* toString(AdmissionStatus value) noexcept
{
    switch (value)
    {
    case AdmissionStatus::accepted: return "accepted";
    case AdmissionStatus::queueFull: return "queue-full";
    case AdmissionStatus::circuitOpen: return "circuit-open";
    case AdmissionStatus::shuttingDown: return "shutting-down";
    case AdmissionStatus::invalid: return "invalid";
    }
    return "invalid";
}

const char* toString(CompletionStatus value) noexcept
{
    switch (value)
    {
    case CompletionStatus::succeeded: return "succeeded";
    case CompletionStatus::failed: return "failed";
    case CompletionStatus::queueTimedOut: return "queue-timed-out";
    case CompletionStatus::executionTimedOut: return "execution-timed-out";
    case CompletionStatus::circuitOpen: return "circuit-open";
    case CompletionStatus::cancelled: return "cancelled";
    }
    return "failed";
}

const char* toString(CircuitState value) noexcept
{
    switch (value)
    {
    case CircuitState::closed: return "closed";
    case CircuitState::open: return "open";
    case CircuitState::halfOpen: return "half-open";
    }
    return "closed";
}

CancellationToken::CancellationToken(std::shared_ptr<std::atomic<bool>> requested)
    : _requested(std::move(requested))
{
}

bool CancellationToken::requested() const noexcept
{
    return _requested && _requested->load(std::memory_order_acquire);
}

struct ResourceGovernor::Impl
{
    struct QueuedWork
    {
        WorkItem item;
        Clock::time_point enqueuedAt;
        bool circuitProbe{false};
    };

    struct ActiveWork
    {
        std::shared_ptr<std::atomic<bool>> cancellation;
        Clock::time_point deadline;
        bool timeoutSignalled{false};
    };

    struct Scope
    {
        explicit Scope(Policy value): policy(std::move(value)) {}

        Policy policy;
        mutable std::mutex mutex;
        std::condition_variable workAvailable;
        std::condition_variable deadlineChanged;
        std::deque<QueuedWork> queue;
        std::map<std::uint64_t, ActiveWork> activeWork;
        std::vector<std::thread> workers;
        std::thread deadlineMonitor;
        bool stopping{false};
        CircuitState circuit{CircuitState::closed};
        bool halfOpenProbeInFlight{false};
        Clock::time_point openedAt{};
        std::uint64_t nextActiveId{1};
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

    explicit Impl(Policy defaultValue, std::vector<Policy> overrideValues)
        : defaultPolicy(std::move(defaultValue))
    {
        defaultPolicy.owner = "*";
        validatePolicy(defaultPolicy, false);
        for (auto& policy : overrideValues)
        {
            validatePolicy(policy, true);
            if (!overrides.emplace(policy.owner, std::move(policy)).second)
                throw std::invalid_argument("duplicate resource governance policy owner");
        }
    }

    Policy policyFor(const std::string& owner) const
    {
        const auto found = overrides.find(owner);
        Policy policy = found == overrides.end() ? defaultPolicy : found->second;
        policy.owner = owner;
        return policy;
    }

    std::shared_ptr<Scope> findScope(const std::string& owner) const
    {
        std::lock_guard<std::mutex> lock(scopesMutex);
        const auto found = scopes.find(owner);
        return found == scopes.end() ? nullptr : found->second;
    }

    std::shared_ptr<Scope> scopeFor(const std::string& owner)
    {
        std::lock_guard<std::mutex> lock(scopesMutex);
        if (stopping) return nullptr;
        const auto found = scopes.find(owner);
        if (found != scopes.end()) return found->second;
        auto scope = std::make_shared<Scope>(policyFor(owner));
        start(scope);
        scopes.emplace(owner, scope);
        return scope;
    }

    static void start(const std::shared_ptr<Scope>& scope)
    {
        scope->workers.reserve(scope->policy.maximumConcurrency);
        try
        {
            scope->deadlineMonitor = std::thread([scope] { monitorDeadlines(scope); });
            for (std::size_t index = 0; index < scope->policy.maximumConcurrency; ++index)
                scope->workers.emplace_back([scope] { worker(scope); });
        }
        catch (...)
        {
            stop(scope, ShutdownMode::cancelPending);
            throw;
        }
    }

    static void monitorDeadlines(const std::shared_ptr<Scope>& scope)
    {
        std::unique_lock<std::mutex> lock(scope->mutex);
        while (true)
        {
            if (scope->activeWork.empty())
            {
                if (scope->stopping && scope->queue.empty()) return;
                scope->deadlineChanged.wait(lock,
                    [&] {
                        return !scope->activeWork.empty() ||
                               (scope->stopping && scope->queue.empty());
                    });
                continue;
            }
            auto earliest = scope->activeWork.end();
            for (auto item = scope->activeWork.begin(); item != scope->activeWork.end(); ++item)
                if (!item->second.timeoutSignalled &&
                    (earliest == scope->activeWork.end() ||
                     item->second.deadline < earliest->second.deadline))
                    earliest = item;
            if (earliest == scope->activeWork.end())
            {
                scope->deadlineChanged.wait(lock);
                continue;
            }
            const auto deadline = earliest->second.deadline;
            if (scope->deadlineChanged.wait_until(lock, deadline) != std::cv_status::timeout)
                continue;
            const auto now = Clock::now();
            for (auto& item : scope->activeWork)
                if (!item.second.timeoutSignalled && item.second.deadline <= now)
                {
                    item.second.cancellation->store(true, std::memory_order_release);
                    item.second.timeoutSignalled = true;
                }
        }
    }

    static std::vector<QueuedWork> openCircuit(Scope& scope, Clock::time_point now)
    {
        scope.circuit = CircuitState::open;
        scope.openedAt = now;
        scope.halfOpenProbeInFlight = false;
        std::vector<QueuedWork> cancelled;
        cancelled.reserve(scope.queue.size());
        while (!scope.queue.empty())
        {
            cancelled.push_back(std::move(scope.queue.front()));
            scope.queue.pop_front();
            ++scope.cancelled;
        }
        return cancelled;
    }

    static void worker(const std::shared_ptr<Scope>& scope)
    {
        while (true)
        {
            QueuedWork queued;
            std::uint64_t activeId = 0;
            auto cancellation = std::make_shared<std::atomic<bool>>(false);
            {
                std::unique_lock<std::mutex> lock(scope->mutex);
                scope->workAvailable.wait(lock,
                    [&] { return scope->stopping || !scope->queue.empty(); });
                if (scope->queue.empty())
                {
                    if (scope->stopping) return;
                    continue;
                }
                queued = std::move(scope->queue.front());
                scope->queue.pop_front();
                scope->deadlineChanged.notify_one();
                const auto now = Clock::now();
                if (now - queued.enqueuedAt >= scope->policy.queueTimeout)
                {
                    ++scope->queueTimedOut;
                    if (queued.circuitProbe) scope->halfOpenProbeInFlight = false;
                    lock.unlock();
                    notify(queued.item,
                        {scope->policy.owner, queued.item.id,
                         CompletionStatus::queueTimedOut,
                         "work exceeded its queue waiting deadline",
                         std::chrono::duration_cast<std::chrono::microseconds>(
                             now - queued.enqueuedAt), std::chrono::microseconds{0}});
                    continue;
                }
                activeId = scope->nextActiveId++;
                scope->activeWork.emplace(activeId,
                    ActiveWork{cancellation, now + scope->policy.executionTimeout, false});
                scope->deadlineChanged.notify_one();
            }

            const auto started = Clock::now();
            bool failed = false;
            std::string failureMessage;
            try
            {
                queued.item.run(CancellationToken(cancellation));
            }
            catch (const std::exception& exception)
            {
                failed = true;
                failureMessage = exception.what();
            }
            catch (...)
            {
                failed = true;
                failureMessage = "governed work threw a non-standard exception";
            }
            const auto finished = Clock::now();
            const bool timedOut = cancellation->load(std::memory_order_acquire) ||
                                  finished - started >= scope->policy.executionTimeout;
            CompletionStatus status = CompletionStatus::succeeded;
            std::vector<QueuedWork> circuitCancelled;
            {
                std::lock_guard<std::mutex> lock(scope->mutex);
                scope->activeWork.erase(activeId);
                scope->deadlineChanged.notify_one();
                if (timedOut)
                {
                    status = CompletionStatus::executionTimedOut;
                    ++scope->executionTimedOut;
                }
                else if (failed)
                {
                    status = CompletionStatus::failed;
                    ++scope->failed;
                }
                else
                {
                    ++scope->succeeded;
                }

                if (status == CompletionStatus::succeeded)
                {
                    if (queued.circuitProbe)
                    {
                        scope->circuit = CircuitState::closed;
                        scope->halfOpenProbeInFlight = false;
                        scope->consecutiveFailures = 0;
                    }
                    else if (scope->circuit == CircuitState::closed)
                    {
                        scope->consecutiveFailures = 0;
                    }
                }
                else if (scope->circuit != CircuitState::open)
                {
                    ++scope->consecutiveFailures;
                    if (queued.circuitProbe ||
                        scope->consecutiveFailures >= scope->policy.failureThreshold)
                        circuitCancelled = openCircuit(*scope, finished);
                    else if (queued.circuitProbe)
                        scope->halfOpenProbeInFlight = false;
                }
            }
            notify(queued.item,
                {scope->policy.owner, queued.item.id, status,
                 timedOut ? "work exceeded its cooperative execution deadline" : failureMessage,
                 std::chrono::duration_cast<std::chrono::microseconds>(started - queued.enqueuedAt),
                 std::chrono::duration_cast<std::chrono::microseconds>(finished - started)});
            for (const auto& cancelled : circuitCancelled)
                notify(cancelled.item,
                    {scope->policy.owner, cancelled.item.id, CompletionStatus::circuitOpen,
                     "work cancelled because the owner circuit opened",
                     std::chrono::duration_cast<std::chrono::microseconds>(
                         finished - cancelled.enqueuedAt), std::chrono::microseconds{0}});
        }
    }

    Admission submit(const std::string& owner, WorkItem item)
    {
        if (owner.empty() || item.id.empty() || !item.run)
            return {AdmissionStatus::invalid, owner, item.id,
                    "owner, work id, and work callback are required"};
        const auto workId = item.id;
        auto scope = scopeFor(owner);
        if (!scope)
            return {AdmissionStatus::shuttingDown, owner, item.id,
                    "resource governor is shutting down"};
        const auto now = Clock::now();
        {
            std::lock_guard<std::mutex> lock(scope->mutex);
            ++scope->submitted;
            if (scope->stopping)
                return {AdmissionStatus::shuttingDown, owner, item.id,
                        "owner lane is shutting down"};
            bool circuitProbe = false;
            if (scope->circuit == CircuitState::open)
            {
                if (now - scope->openedAt < scope->policy.circuitResetTimeout)
                {
                    ++scope->rejectedCircuitOpen;
                    return {AdmissionStatus::circuitOpen, owner, item.id,
                            "owner circuit is open"};
                }
                scope->circuit = CircuitState::halfOpen;
                scope->halfOpenProbeInFlight = false;
            }
            if (scope->circuit == CircuitState::halfOpen)
            {
                if (scope->halfOpenProbeInFlight)
                {
                    ++scope->rejectedCircuitOpen;
                    return {AdmissionStatus::circuitOpen, owner, item.id,
                            "owner circuit is waiting for its half-open probe"};
                }
                scope->halfOpenProbeInFlight = true;
                circuitProbe = true;
            }
            if (scope->queue.size() >= scope->policy.queueCapacity)
            {
                if (circuitProbe) scope->halfOpenProbeInFlight = false;
                ++scope->rejectedQueueFull;
                return {AdmissionStatus::queueFull, owner, item.id,
                        "owner queue capacity has been reached"};
            }
            scope->queue.push_back({std::move(item), now, circuitProbe});
            ++scope->accepted;
        }
        scope->workAvailable.notify_one();
        return {AdmissionStatus::accepted, owner, workId, "accepted"};
    }

    static Snapshot snapshotOf(const std::shared_ptr<Scope>& scope)
    {
        std::lock_guard<std::mutex> lock(scope->mutex);
        CircuitState circuit = scope->circuit;
        if (circuit == CircuitState::open &&
            Clock::now() - scope->openedAt >= scope->policy.circuitResetTimeout)
            circuit = CircuitState::halfOpen;
        return {scope->policy, circuit, scope->stopping, scope->activeWork.size(),
                scope->queue.size(), scope->consecutiveFailures, scope->submitted,
                scope->accepted, scope->rejectedQueueFull, scope->rejectedCircuitOpen,
                scope->queueTimedOut, scope->executionTimedOut, scope->succeeded,
                scope->failed, scope->cancelled};
    }

    static void stop(const std::shared_ptr<Scope>& scope, ShutdownMode mode) noexcept
    {
        std::deque<QueuedWork> cancelled;
        {
            std::lock_guard<std::mutex> lock(scope->mutex);
            if (scope->stopping) return;
            scope->stopping = true;
            if (mode == ShutdownMode::cancelPending)
            {
                for (auto& active : scope->activeWork)
                    active.second.cancellation->store(true, std::memory_order_release);
                cancelled.swap(scope->queue);
                scope->cancelled += cancelled.size();
            }
        }
        for (const auto& item : cancelled)
            notify(item.item,
                {scope->policy.owner, item.item.id, CompletionStatus::cancelled,
                 "work cancelled during resource governor shutdown",
                 std::chrono::duration_cast<std::chrono::microseconds>(
                     Clock::now() - item.enqueuedAt), std::chrono::microseconds{0}});
        scope->workAvailable.notify_all();
        scope->deadlineChanged.notify_all();
        for (auto& worker : scope->workers)
            if (worker.joinable()) worker.join();
        if (scope->deadlineMonitor.joinable()) scope->deadlineMonitor.join();
    }

    void shutdown(ShutdownMode mode) noexcept
    {
        std::vector<std::shared_ptr<Scope>> values;
        {
            std::lock_guard<std::mutex> lock(scopesMutex);
            if (stopping) return;
            stopping = true;
            values.reserve(scopes.size());
            for (const auto& item : scopes) values.push_back(item.second);
        }
        for (const auto& scope : values) stop(scope, mode);
    }

    Policy defaultPolicy;
    std::unordered_map<std::string, Policy> overrides;
    mutable std::mutex scopesMutex;
    std::unordered_map<std::string, std::shared_ptr<Scope>> scopes;
    bool stopping{false};
};

ResourceGovernor::ResourceGovernor(Policy defaultPolicy, std::vector<Policy> overrides)
    : _impl(std::make_unique<Impl>(std::move(defaultPolicy), std::move(overrides)))
{
}

ResourceGovernor::~ResourceGovernor() { shutdown(); }

Admission ResourceGovernor::submit(const std::string& owner, WorkItem item)
{
    const auto workId = item.id;
    auto admission = _impl->submit(owner, std::move(item));
    admission.workId = workId;
    return admission;
}

Snapshot ResourceGovernor::snapshot(const std::string& owner) const
{
    if (owner.empty()) throw std::invalid_argument("resource owner is required");
    const auto scope = _impl->findScope(owner);
    if (scope) return Impl::snapshotOf(scope);
    Snapshot result;
    result.policy = _impl->policyFor(owner);
    return result;
}

std::vector<Snapshot> ResourceGovernor::snapshots() const
{
    std::vector<std::shared_ptr<Impl::Scope>> scopes;
    {
        std::lock_guard<std::mutex> lock(_impl->scopesMutex);
        scopes.reserve(_impl->scopes.size());
        for (const auto& item : _impl->scopes) scopes.push_back(item.second);
    }
    std::vector<Snapshot> result;
    result.reserve(scopes.size());
    for (const auto& scope : scopes) result.push_back(Impl::snapshotOf(scope));
    std::sort(result.begin(), result.end(),
              [](const auto& left, const auto& right)
              { return left.policy.owner < right.policy.owner; });
    return result;
}

void ResourceGovernor::shutdown(ShutdownMode mode) noexcept
{
    if (_impl) _impl->shutdown(mode);
}
} // namespace PocoDDS::ResourceGovernance
