#include "PocoDDS/ResourceGovernance/ManagedWorkLane.h"

#include <condition_variable>
#include <exception>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <utility>

namespace PocoDDS::ResourceGovernance
{
struct ManagedWorkLane::State
{
    mutable std::mutex mutex;
    std::condition_variable changed;
    bool accepting{true};
    std::size_t outstanding{0};
};

namespace
{
struct Callbacks
{
    std::function<void(const CancellationToken&)> run;
    std::function<void(const Completion&)> complete;
};
} // namespace

void ManagedWorkLane::finish(const std::shared_ptr<State>& state) noexcept
{
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        if (state->outstanding > 0) --state->outstanding;
    }
    state->changed.notify_all();
}

ManagedWorkLane::ManagedWorkLane(ResourceGovernorService::Ptr service,
                                 std::string owner)
    : _service(std::move(service)), _owner(std::move(owner)),
      _state(std::make_shared<State>())
{
    if (!_service) throw std::invalid_argument("resource governor service is required");
    if (_owner.empty()) throw std::invalid_argument("resource governance owner is required");
}

ManagedWorkLane::~ManagedWorkLane()
{
    closeAndWait();
}

Admission ManagedWorkLane::submit(WorkItem item)
{
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        if (!_state->accepting)
            return {AdmissionStatus::shuttingDown, _owner, item.id,
                    "managed owner lane is closed"};
        ++_state->outstanding;
    }

    const auto state = _state;
    auto callbacks = std::make_shared<Callbacks>();
    callbacks->run = std::move(item.run);
    callbacks->complete = std::move(item.complete);
    item.run = [callbacks](const CancellationToken& token) {
        if (callbacks->run) callbacks->run(token);
    };
    item.complete = [state, callbacks](const Completion& value) {
        std::exception_ptr failure;
        try
        {
            if (callbacks->complete) callbacks->complete(value);
        }
        catch (...)
        {
            failure = std::current_exception();
        }
        // Destroy Bundle-owned callback targets before releasing the unload barrier.
        callbacks->run = {};
        callbacks->complete = {};
        finish(state);
        if (failure) std::rethrow_exception(failure);
    };

    try
    {
        auto admission = _service->submit(_owner, std::move(item));
        if (admission.status != AdmissionStatus::accepted) finish(state);
        return admission;
    }
    catch (...)
    {
        finish(state);
        throw;
    }
}

void ManagedWorkLane::closeAndWait() noexcept
{
    if (!_state) return;
    std::unique_lock<std::mutex> lock(_state->mutex);
    _state->accepting = false;
    _state->changed.wait(lock, [&] { return _state->outstanding == 0; });
}

const std::string& ManagedWorkLane::owner() const noexcept
{
    return _owner;
}

bool ManagedWorkLane::accepting() const noexcept
{
    std::lock_guard<std::mutex> lock(_state->mutex);
    return _state->accepting;
}

std::size_t ManagedWorkLane::outstanding() const noexcept
{
    std::lock_guard<std::mutex> lock(_state->mutex);
    return _state->outstanding;
}
} // namespace PocoDDS::ResourceGovernance
