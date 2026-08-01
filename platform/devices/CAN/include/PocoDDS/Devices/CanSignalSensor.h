#pragma once

#include "PocoDDS/Devices/Sensor.h"
#include "PocoDDS/Protocols/CAN/SignalCodec.h"
#include "PocoDDS/Protocols/CAN/SocketCanEndpoint.h"

#include <Poco/Mutex.h>
#include <Poco/Thread.h>

#include <atomic>
#include <chrono>
#include <memory>
#include <string>

namespace PocoDDS::Devices
{
struct CanRecoveryPolicy
{
    bool enabled{true};
    std::chrono::milliseconds reconnectDelay{250};
    std::chrono::milliseconds receiveTimeout{250};
    std::chrono::milliseconds staleAfter{2000};
};

class CanSignalSensor final : public Sensor, public DiagnosticDevice
{
public:
    struct Options
    {
        std::string id;
        std::string interfaceName;
        std::uint32_t frameId{0};
        bool extended{false};
        std::size_t bitOffset{0};
        std::size_t bitLength{1};
        PocoDDS::Protocols::CAN::BitOrder bitOrder{
            PocoDDS::Protocols::CAN::BitOrder::littleEndian};
        bool signedValue{false};
        double factor{1};
        double offset{0};
        std::string physicalQuantity;
        std::string physicalUnit;
    };

    explicit CanSignalSensor(Options options, CanRecoveryPolicy recoveryPolicy = {});
    CanSignalSensor(Options options,
                    std::shared_ptr<PocoDDS::Protocols::CAN::CanEndpoint> endpoint,
                    CanRecoveryPolicy recoveryPolicy = {});
    ~CanSignalSensor() override;

    const std::string& id() const noexcept override;
    const std::string& type() const noexcept override;
    void start() override;
    void stop() noexcept override;
    DeviceSnapshot snapshot() const override;
    std::string execute(const std::string& operation, const std::string& payload) override;
    void setSnapshotHandler(SnapshotHandler handler) override;
    double value() const override;
    std::string physicalQuantity() const override;
    std::string physicalUnit() const override;
    void setValueHandler(ValueHandler handler) override;
    bool ingest(const PocoDDS::Protocols::CAN::CanFrame& frame);
    DeviceDiagnostics diagnostics() const override;

private:
    void run();
    void markTransportFailure(const std::string& message);
    void markConnected();
    void checkStale();
    void notify(const DeviceSnapshot& snapshot, bool notifyValue);
    Options _options;
    CanRecoveryPolicy _recoveryPolicy;
    std::string _type{"sensor.can.signal"};
    std::shared_ptr<PocoDDS::Protocols::CAN::CanEndpoint> _endpoint;
    std::atomic_bool _running{false};
    mutable Poco::FastMutex _mutex;
    Poco::Thread _thread;
    DeviceState _state{DeviceState::offline};
    double _value{0};
    std::uint64_t _sequence{0};
    std::string _lastPayload{"no-frame"};
    std::chrono::steady_clock::time_point _lastFrame;
    DeviceDiagnostics _diagnostics;
    SnapshotHandler _snapshotHandler;
    ValueHandler _valueHandler;
};
} // namespace PocoDDS::Devices
