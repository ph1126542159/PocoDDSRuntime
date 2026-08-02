#pragma once

#include "PocoDDS/Reliability/Reliability.h"

#include <cstdint>
#include <functional>
#include <string>
#include <utility>

namespace PocoDDS::Devices
{
enum class DeviceState
{
    offline,
    ready,
    fault
};

struct DeviceSnapshot
{
    std::string id;
    std::string type;
    DeviceState state{DeviceState::offline};
    std::uint64_t sequence{0};
    std::int64_t timestampMicroseconds{0};
    std::string payload;
};

class Device
{
public:
    using SnapshotHandler = std::function<void(const DeviceSnapshot&)>;

    virtual ~Device() = default;

    virtual const std::string& id() const noexcept = 0;
    virtual const std::string& type() const noexcept = 0;
    virtual void start() = 0;
    virtual void stop() noexcept = 0;
    virtual DeviceSnapshot snapshot() const = 0;
    virtual std::string execute(const std::string& operation, const std::string& payload) = 0;
    virtual void setSnapshotHandler(SnapshotHandler handler) = 0;
};

struct DeviceDiagnostics
{
    std::uint64_t successfulOperations{0};
    std::uint64_t failedOperations{0};
    std::uint64_t reconnectAttempts{0};
    std::uint64_t consecutiveFailures{0};
    std::int64_t lastSuccessMicroseconds{0};
    std::int64_t lastFailureMicroseconds{0};
    std::string lastError;
};

inline void resolveFailure(DeviceDiagnostics& diagnostics,
                           PocoDDS::Reliability::Failure& failure) noexcept
{
    diagnostics.lastError.clear();
    PocoDDS::Reliability::resolve(failure);
}

inline void recordFailure(DeviceDiagnostics& diagnostics,
                          PocoDDS::Reliability::Failure& failure,
                          std::string code, PocoDDS::Reliability::FailureKind kind,
                          bool retryable, std::string message)
{
    diagnostics.lastError = message;
    failure = PocoDDS::Reliability::makeFailure(
        std::move(code), kind, retryable, std::move(message));
}

// Optional capability. Keeping diagnostics separate from Device preserves the
// ABI of existing third-party device implementations.
class DiagnosticDevice
{
public:
    virtual ~DiagnosticDevice() = default;
    virtual DeviceDiagnostics diagnostics() const = 0;
};

// Optional versioned extension. It is separate from DiagnosticDevice so
// adding structured failures does not change existing third-party vtables or
// the DeviceDiagnostics return layout.
class FailureDiagnosticDevice
{
public:
    virtual ~FailureDiagnosticDevice() = default;
    virtual PocoDDS::Reliability::Failure failure() const = 0;
};

const char* toString(DeviceState state) noexcept;
} // namespace PocoDDS::Devices
