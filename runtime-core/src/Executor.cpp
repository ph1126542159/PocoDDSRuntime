#include "PocoDDS/RuntimeCore/Executor.h"

#include <condition_variable>
#include <deque>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

namespace PocoDDS::RuntimeCore
{
namespace
{
RuntimeError queueError(RuntimeErrorCode code, std::string message, bool retryable)
{
    return {code, std::move(message), retryable};
}

void cancelTask(ExecutorTask& task, RuntimeError error) noexcept
{
    if (!task.cancel)
        return;
    try
    {
        task.cancel(std::move(error));
    }
    catch (...)
    {
    }
}
} // namespace

SubmitStatus InlineExecutor::submit(ExecutorTask task)
{
    if (!task.run)
    {
        cancelTask(task, queueError(RuntimeErrorCode::invalidArgument,
                                    "executor task cannot be empty", false));
        return SubmitStatus::rejected;
    }
    if (_stopped.load(std::memory_order_acquire))
    {
        cancelTask(task, queueError(RuntimeErrorCode::stopped, "executor has stopped", false));
        return SubmitStatus::stopped;
    }
    try
    {
        task.run();
        return SubmitStatus::accepted;
    }
    catch (...)
    {
        cancelTask(
            task, queueError(RuntimeErrorCode::internalError, "inline executor task threw", false));
        return SubmitStatus::executionFailed;
    }
}

void InlineExecutor::shutdown(ShutdownMode) noexcept
{
    _stopped.store(true, std::memory_order_release);
}

std::size_t InlineExecutor::pending() const noexcept { return 0; }

struct ThreadPoolExecutor::State
{
    explicit State(Options value) : options(std::move(value)) {}

    Options options;
    mutable std::mutex mutex;
    std::condition_variable workAvailable;
    std::condition_variable spaceAvailable;
    std::deque<ExecutorTask> queue;
    std::vector<std::thread> workers;
    std::once_flag shutdownOnce;
    bool stopping{false};
};

ThreadPoolExecutor::ThreadPoolExecutor(Options options)
    : _state(std::make_shared<State>(std::move(options)))
{
    if (_state->options.workerCount == 0)
        throw std::invalid_argument("thread pool workerCount must be positive");
    if (_state->options.queueCapacity == 0)
        throw std::invalid_argument("thread pool queueCapacity must be positive");
    if (_state->options.blockTimeout.count() < 0)
        throw std::invalid_argument("thread pool blockTimeout cannot be negative");

    const auto state = _state;
    state->workers.reserve(state->options.workerCount);
    try
    {
        for (std::size_t index = 0; index < state->options.workerCount; ++index)
        {
            state->workers.emplace_back(
                [state]
                {
                    while (true)
                    {
                        ExecutorTask task;
                        {
                            std::unique_lock<std::mutex> lock(state->mutex);
                            state->workAvailable.wait(
                                lock, [&] { return state->stopping || !state->queue.empty(); });
                            if (state->queue.empty())
                            {
                                if (state->stopping)
                                    return;
                                continue;
                            }
                            task = std::move(state->queue.front());
                            state->queue.pop_front();
                            state->spaceAvailable.notify_one();
                        }
                        try
                        {
                            task.run();
                        }
                        catch (...)
                        {
                            cancelTask(task, queueError(RuntimeErrorCode::internalError,
                                                        "thread pool task threw", false));
                        }
                    }
                });
        }
    }
    catch (...)
    {
        {
            std::lock_guard<std::mutex> lock(state->mutex);
            state->stopping = true;
        }
        state->workAvailable.notify_all();
        for (auto& worker : state->workers)
        {
            if (worker.joinable())
                worker.join();
        }
        throw;
    }
}

ThreadPoolExecutor::~ThreadPoolExecutor() { shutdown(ShutdownMode::drain); }

SubmitStatus ThreadPoolExecutor::submit(ExecutorTask task)
{
    if (!task.run)
    {
        cancelTask(task, queueError(RuntimeErrorCode::invalidArgument,
                                    "executor task cannot be empty", false));
        return SubmitStatus::rejected;
    }

    ExecutorTask displaced;
    SubmitStatus status = SubmitStatus::accepted;
    {
        std::unique_lock<std::mutex> lock(_state->mutex);
        if (_state->stopping)
        {
            lock.unlock();
            cancelTask(task, queueError(RuntimeErrorCode::stopped, "executor has stopped", false));
            return SubmitStatus::stopped;
        }

        const auto full = [&] { return _state->queue.size() >= _state->options.queueCapacity; };
        if (full())
        {
            switch (_state->options.overflowPolicy)
            {
            case OverflowPolicy::rejectNewest:
                lock.unlock();
                cancelTask(task,
                           queueError(RuntimeErrorCode::queueFull, "executor queue is full", true));
                return SubmitStatus::rejected;
            case OverflowPolicy::dropOldest:
                displaced = std::move(_state->queue.front());
                _state->queue.pop_front();
                status = SubmitStatus::acceptedAfterDroppingOldest;
                break;
            case OverflowPolicy::blockPublisher:
                if (!_state->spaceAvailable.wait_for(lock, _state->options.blockTimeout,
                                                     [&] { return _state->stopping || !full(); }))
                {
                    lock.unlock();
                    cancelTask(task,
                               queueError(RuntimeErrorCode::timeout,
                                          "timed out waiting for executor queue space", true));
                    return SubmitStatus::timedOut;
                }
                if (_state->stopping)
                {
                    lock.unlock();
                    cancelTask(task,
                               queueError(RuntimeErrorCode::stopped,
                                          "executor stopped while publisher was blocked", false));
                    return SubmitStatus::stopped;
                }
                break;
            }
        }
        _state->queue.push_back(std::move(task));
    }

    if (displaced.run)
        cancelTask(displaced, queueError(RuntimeErrorCode::queueFull,
                                         "executor dropped the oldest queued task", true));
    _state->workAvailable.notify_one();
    return status;
}

void ThreadPoolExecutor::shutdown(ShutdownMode mode) noexcept
{
    if (!_state)
        return;

    const auto state = _state;
    std::call_once(state->shutdownOnce,
                   [state, mode]
                   {
                       std::deque<ExecutorTask> cancelled;
                       {
                           std::lock_guard<std::mutex> lock(state->mutex);
                           state->stopping = true;
                           if (mode == ShutdownMode::cancelPending)
                               cancelled.swap(state->queue);
                       }
                       for (auto& task : cancelled)
                           cancelTask(task,
                                      queueError(RuntimeErrorCode::cancelled,
                                                 "executor cancelled pending task during shutdown",
                                                 false));
                       state->workAvailable.notify_all();
                       state->spaceAvailable.notify_all();
                       const auto current = std::this_thread::get_id();
                       for (auto& worker : state->workers)
                       {
                           if (!worker.joinable())
                               continue;
                           if (worker.get_id() == current)
                               worker.detach();
                           else
                               worker.join();
                       }
                       state->workers.clear();
                   });
}

std::size_t ThreadPoolExecutor::pending() const noexcept
{
    std::lock_guard<std::mutex> lock(_state->mutex);
    return _state->queue.size();
}

} // namespace PocoDDS::RuntimeCore
