#pragma once

#include <chrono>
#include <functional>
#include <mutex>
#include <string>

namespace PocoDDS::Protocols
{
struct ProtocolMetricEvent
{
    std::string protocol;
    std::string operation;
    std::string result;
    double durationMilliseconds{0};
    std::size_t bytes{0};
};

class ProtocolMetrics
{
public:
    using Sink = std::function<void(const ProtocolMetricEvent&)>;

    static void setSink(Sink sink)
    {
        std::lock_guard<std::mutex> lock(mutex());
        target() = std::move(sink);
    }

    static void emit(ProtocolMetricEvent event) noexcept
    {
        try
        {
            Sink copy;
            {
                std::lock_guard<std::mutex> lock(mutex());
                copy = target();
            }
            if (copy) copy(event);
        }
        catch (...) {}
    }

private:
    static Sink& target() { static Sink value; return value; }
    static std::mutex& mutex() { static std::mutex value; return value; }
};

class ProtocolMetricTimer
{
public:
    ProtocolMetricTimer(std::string protocol, std::string operation, std::size_t bytes = 0)
        : _protocol(std::move(protocol)), _operation(std::move(operation)), _bytes(bytes),
          _started(std::chrono::steady_clock::now()) {}
    ~ProtocolMetricTimer()
    {
        if (!_finished) finish("error");
    }
    void success() noexcept { finish("success"); }
    void timeout() noexcept { finish("timeout"); }
    void failure() noexcept { finish("error"); }

private:
    void finish(const char* result) noexcept
    {
        if (_finished) return;
        _finished = true;
        ProtocolMetrics::emit({_protocol, _operation, result,
            std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - _started).count(), _bytes});
    }
    std::string _protocol;
    std::string _operation;
    std::size_t _bytes;
    std::chrono::steady_clock::time_point _started;
    bool _finished{false};
};
}
