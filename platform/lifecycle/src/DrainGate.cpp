#include "PocoDDS/Lifecycle/DrainGate.h"

#include <condition_variable>
#include <mutex>
#include <utility>

namespace PocoDDS::Lifecycle
{
struct DrainGate::State
{
    mutable std::mutex mutex;
    std::condition_variable changed;
    DrainState state{DrainState::accepting};
    bool closed{false};
    std::size_t inFlight{0};
    std::uint64_t generation{1};
};

const char* toString(DrainState state) noexcept
{
    switch (state)
    {
    case DrainState::accepting: return "accepting";
    case DrainState::quiescing: return "quiescing";
    case DrainState::quiesced: return "quiesced";
    }
    return "quiescing";
}

DrainGate::Lease::Lease(std::shared_ptr<State> state): _state(std::move(state)) {}

DrainGate::Lease::~Lease() { release(); }

DrainGate::Lease::Lease(Lease&& other) noexcept: _state(std::move(other._state)) {}

DrainGate::Lease& DrainGate::Lease::operator=(Lease&& other) noexcept
{
    if (this != &other)
    {
        release();
        _state = std::move(other._state);
    }
    return *this;
}

void DrainGate::Lease::release() noexcept
{
    if (!_state) return;
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        if (_state->inFlight > 0) --_state->inFlight;
        if (_state->inFlight == 0 && _state->state == DrainState::quiescing)
        {
            _state->state = DrainState::quiesced;
            ++_state->generation;
        }
    }
    _state->changed.notify_all();
    _state.reset();
}

DrainGate::DrainGate(): _state(std::make_shared<State>()) {}
DrainGate::~DrainGate() = default;

std::optional<DrainGate::Lease> DrainGate::tryEnter()
{
    std::lock_guard<std::mutex> lock(_state->mutex);
    if (_state->closed || _state->state != DrainState::accepting)
        return std::nullopt;
    ++_state->inFlight;
    return Lease(_state);
}

bool DrainGate::quiesce(std::chrono::milliseconds timeout) noexcept
{
    if (timeout.count() < 0) timeout = std::chrono::milliseconds::zero();
    std::unique_lock<std::mutex> lock(_state->mutex);
    if (_state->state == DrainState::accepting)
    {
        _state->state = _state->inFlight == 0
            ? DrainState::quiesced
            : DrainState::quiescing;
        ++_state->generation;
    }
    if (_state->state == DrainState::quiesced) return true;
    return _state->changed.wait_for(lock, timeout, [&] {
        return _state->state == DrainState::quiesced;
    });
}

void DrainGate::closeAndWait() noexcept
{
    std::unique_lock<std::mutex> lock(_state->mutex);
    _state->closed = true;
    if (_state->state == DrainState::accepting)
    {
        _state->state = _state->inFlight == 0
            ? DrainState::quiesced
            : DrainState::quiescing;
        ++_state->generation;
    }
    _state->changed.wait(lock, [&] { return _state->inFlight == 0; });
    if (_state->state != DrainState::quiesced)
    {
        _state->state = DrainState::quiesced;
        ++_state->generation;
    }
}

void DrainGate::resume() noexcept
{
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        if (_state->closed) return;
        if (_state->state == DrainState::accepting) return;
        _state->state = DrainState::accepting;
        ++_state->generation;
    }
    _state->changed.notify_all();
}

DrainSnapshot DrainGate::snapshot() const noexcept
{
    std::lock_guard<std::mutex> lock(_state->mutex);
    return {_state->state, _state->state == DrainState::accepting,
            _state->inFlight, _state->generation};
}
} // namespace PocoDDS::Lifecycle
