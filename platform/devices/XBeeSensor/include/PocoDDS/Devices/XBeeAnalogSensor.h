#pragma once

#include "PocoDDS/Devices/Sensor.h"
#include "PocoDDS/Protocols/XBee/IoSample.h"
#include "PocoDDS/Protocols/XBee/XBeePort.h"

#include <Poco/Mutex.h>
#include <Poco/Thread.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <string>

namespace PocoDDS::Devices
{

struct XBeeRecoveryPolicy
{
    bool enabled{true};
    std::chrono::milliseconds reconnectDelay{250};
    std::chrono::milliseconds receiveTimeout{250};
    std::chrono::milliseconds staleAfter{5000};
};

class XBeeAnalogSensor final : public Sensor, public DiagnosticDevice
{
public:
    enum class Conversion
    {
        raw,
        millivolts,
        temperatureCelsius,
        relativeHumidity
    };

    struct Options
    {
        std::string id;
        std::string serialPort;
        int baudRate{9600};
        bool escapedApiMode{false};
        std::uint64_t sourceAddress{0};
        unsigned analogChannel{0};
        Conversion conversion{Conversion::raw};
        std::string physicalQuantity;
        std::string physicalUnit;
        double referenceMillivolts{1200.0};
        double adcMaximum{1023.0};
    };

    explicit XBeeAnalogSensor(Options options, XBeeRecoveryPolicy recoveryPolicy = {});
    XBeeAnalogSensor(
        Options options,
        std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> serial,
        XBeeRecoveryPolicy recoveryPolicy = {});
    ~XBeeAnalogSensor() override;

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
    DeviceDiagnostics diagnostics() const override;

    bool ingest(const PocoDDS::Protocols::XBee::IoSample& sample);

private:
    double convert(std::uint16_t sample) const;
    void run();
    void markConnected();
    void markFailure(const std::string& message, DeviceState state);
    void checkStale();
    void notify(const DeviceSnapshot& snapshot, const double* value = nullptr);

    Options _options;
    std::string _type{"sensor.xbee.analog"};
    std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> _serial;
    std::unique_ptr<PocoDDS::Protocols::XBee::XBeePort> _port;
    XBeeRecoveryPolicy _recoveryPolicy;
    std::atomic_bool _running{false};
    mutable Poco::FastMutex _mutex;
    Poco::Thread _thread;
    DeviceState _state{DeviceState::offline};
    std::chrono::steady_clock::time_point _lastSample;
    double _value{0};
    std::uint64_t _sequence{0};
    DeviceDiagnostics _diagnostics;
    SnapshotHandler _snapshotHandler;
    ValueHandler _valueHandler;
};

} // namespace PocoDDS::Devices
