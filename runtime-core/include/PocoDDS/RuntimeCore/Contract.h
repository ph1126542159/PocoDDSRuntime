#pragma once

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <utility>

namespace PocoDDS::RuntimeCore
{

enum class RuntimeErrorCode
{
    none,
    invalidArgument,
    unsupported,
    timeout,
    cancelled,
    unavailable,
    queueFull,
    stopped,
    dependencyFailure,
    protocolError,
    internalError
};

struct RuntimeError
{
    RuntimeErrorCode code{RuntimeErrorCode::none};
    std::string message;
    bool retryable{false};

    explicit operator bool() const noexcept { return code != RuntimeErrorCode::none; }
};

template <typename T> class Outcome
{
  public:
    static Outcome success(T value) { return Outcome(std::move(value)); }
    static Outcome failure(RuntimeError error) { return Outcome(std::move(error)); }

    explicit operator bool() const noexcept { return _value.has_value(); }
    const T& value() const& { return _value.value(); }
    T& value() & { return _value.value(); }
    T&& value() && { return std::move(_value).value(); }
    const RuntimeError& error() const noexcept { return _error; }

  private:
    explicit Outcome(T value) : _value(std::move(value)) {}
    explicit Outcome(RuntimeError error) : _error(std::move(error)) {}

    std::optional<T> _value;
    RuntimeError _error;
};

template <> class Outcome<void>
{
  public:
    static Outcome success() { return Outcome(true, {}); }
    static Outcome failure(RuntimeError error) { return Outcome(false, std::move(error)); }

    explicit operator bool() const noexcept { return _success; }
    const RuntimeError& error() const noexcept { return _error; }

  private:
    Outcome(bool success, RuntimeError error) : _success(success), _error(std::move(error)) {}

    bool _success{false};
    RuntimeError _error;
};

struct MessageContext
{
    std::string messageId;
    std::string correlationId;
    std::string causationId;
    std::string traceParent;
    std::chrono::steady_clock::time_point deadline{};
    std::uint8_t priority{0};

    bool expired() const noexcept
    {
        return deadline != std::chrono::steady_clock::time_point{} &&
               std::chrono::steady_clock::now() >= deadline;
    }
};

} // namespace PocoDDS::RuntimeCore
