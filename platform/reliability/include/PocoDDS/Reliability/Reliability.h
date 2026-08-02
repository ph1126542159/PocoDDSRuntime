#pragma once

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <deque>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_set>
#include <utility>

namespace PocoDDS::Reliability
{
enum class FailureKind
{
    transient,
    permanent,
    configuration,
    hardware,
    safety
};

inline const char* toString(FailureKind kind) noexcept
{
    switch (kind)
    {
    case FailureKind::transient: return "transient";
    case FailureKind::permanent: return "permanent";
    case FailureKind::configuration: return "configuration";
    case FailureKind::hardware: return "hardware";
    case FailureKind::safety: return "safety";
    }
    return "permanent";
}

struct Failure
{
    std::string code;
    FailureKind kind{FailureKind::permanent};
    bool retryable{false};
    bool active{false};
    std::int64_t occurredAtMicroseconds{0};
    std::string message;
};

inline Failure makeFailure(std::string code, FailureKind kind, bool retryable,
                           std::string message)
{
    const auto now = std::chrono::system_clock::now().time_since_epoch();
    return {std::move(code), kind, retryable, true,
            std::chrono::duration_cast<std::chrono::microseconds>(now).count(),
            std::move(message)};
}

inline void resolve(Failure& failure) noexcept
{
    failure.active = false;
}

class Deadline
{
public:
    explicit Deadline(std::chrono::milliseconds timeout):
        _expiresAt(std::chrono::steady_clock::now() + timeout)
    {
    }
    [[nodiscard]] bool expired() const noexcept
    {
        return std::chrono::steady_clock::now() >= _expiresAt;
    }
    [[nodiscard]] std::chrono::milliseconds remaining() const noexcept
    {
        const auto value = std::chrono::duration_cast<std::chrono::milliseconds>(
            _expiresAt - std::chrono::steady_clock::now());
        return value.count() > 0 ? value : std::chrono::milliseconds(0);
    }

private:
    std::chrono::steady_clock::time_point _expiresAt;
};

struct RetryPolicy
{
    std::size_t maxAttempts{3};
    std::chrono::milliseconds initialDelay{100};
    std::chrono::milliseconds maxDelay{5000};
    double multiplier{2.0};

    [[nodiscard]] std::chrono::milliseconds delayFor(std::size_t attempt) const noexcept
    {
        double delay = static_cast<double>(initialDelay.count());
        for (std::size_t index = 1; index < attempt; ++index)
            delay *= multiplier;
        return std::chrono::milliseconds(
            std::min<long long>(static_cast<long long>(delay), maxDelay.count()));
    }
};

class CircuitBreaker
{
public:
    CircuitBreaker(std::size_t failureThreshold, std::chrono::milliseconds resetTimeout):
        _failureThreshold(failureThreshold), _resetTimeout(resetTimeout)
    {
    }

    [[nodiscard]] bool allow(std::chrono::steady_clock::time_point now) const noexcept
    {
        return !_openedAt || now - *_openedAt >= _resetTimeout;
    }

    void success() noexcept
    {
        _failures = 0;
        _openedAt.reset();
    }

    void failure(std::chrono::steady_clock::time_point now) noexcept
    {
        if (++_failures >= _failureThreshold)
            _openedAt = now;
    }

private:
    std::size_t _failureThreshold;
    std::chrono::milliseconds _resetTimeout;
    std::size_t _failures{0};
    std::optional<std::chrono::steady_clock::time_point> _openedAt;
};

class IdempotencyWindow
{
public:
    explicit IdempotencyWindow(std::size_t capacity): _capacity(capacity) {}

    bool accept(const std::string& key)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (_keys.find(key) != _keys.end())
            return false;
        _keys.insert(key);
        _order.push_back(key);
        if (_order.size() > _capacity)
        {
            _keys.erase(_order.front());
            _order.pop_front();
        }
        return true;
    }

private:
    std::size_t _capacity;
    std::mutex _mutex;
    std::unordered_set<std::string> _keys;
    std::deque<std::string> _order;
};

class Bulkhead
{
public:
    explicit Bulkhead(std::size_t limit): _limit(limit) {}

    bool tryAcquire()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (_active >= _limit)
            return false;
        ++_active;
        return true;
    }

    void release()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (_active > 0)
            --_active;
    }

    [[nodiscard]] std::size_t active() const
    {
        std::lock_guard<std::mutex> lock(_mutex);
        return _active;
    }

private:
    std::size_t _limit;
    mutable std::mutex _mutex;
    std::size_t _active{0};
};

template <typename T>
class BoundedQueue
{
public:
    explicit BoundedQueue(std::size_t capacity): _capacity(capacity) {}

    bool tryPush(T value)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (_closed || _queue.size() >= _capacity)
            return false;
        _queue.push_back(std::move(value));
        _available.notify_one();
        return true;
    }

    std::optional<T> pop(std::chrono::milliseconds timeout)
    {
        std::unique_lock<std::mutex> lock(_mutex);
        _available.wait_for(lock, timeout, [&] { return _closed || !_queue.empty(); });
        if (_queue.empty())
            return std::nullopt;
        T value = std::move(_queue.front());
        _queue.pop_front();
        return value;
    }

    void close()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _closed = true;
        _available.notify_all();
    }

    [[nodiscard]] std::size_t size() const
    {
        std::lock_guard<std::mutex> lock(_mutex);
        return _queue.size();
    }

private:
    std::size_t _capacity;
    mutable std::mutex _mutex;
    std::condition_variable _available;
    std::deque<T> _queue;
    bool _closed{false};
};

class Lease
{
public:
    explicit Lease(std::chrono::milliseconds ttl): _ttl(ttl) { renew(); }
    void renew() noexcept { _expiresAt = std::chrono::steady_clock::now() + _ttl; }
    [[nodiscard]] bool valid() const noexcept
    {
        return std::chrono::steady_clock::now() < _expiresAt;
    }

private:
    std::chrono::milliseconds _ttl;
    std::chrono::steady_clock::time_point _expiresAt;
};

class ShutdownSignal
{
public:
    void request() noexcept { _requested.store(true); }
    [[nodiscard]] bool requested() const noexcept { return _requested.load(); }

private:
    std::atomic<bool> _requested{false};
};
}
