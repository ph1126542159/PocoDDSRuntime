#pragma once

#include "PocoDDS/Devices/Sensor.h"
#include "PocoDDS/Protocols/XBee/IoSample.h"
#include "PocoDDS/Protocols/XBee/XBeePort.h"

#include <Poco/Mutex.h>
#include <Poco/Thread.h>

#include <atomic>
#include <cstdint>
#include <memory>
#include <string>

namespace PocoDDS::Devices
{

class XBeeAnalogSensor final : public Sensor
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

    explicit XBeeAnalogSensor(Options options);
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

    bool ingest(const PocoDDS::Protocols::XBee::IoSample& sample);

private:
    double convert(std::uint16_t sample) const;
    void run();

    Options _options;
    std::string _type{"sensor.xbee.analog"};
    std::shared_ptr<PocoDDS::Protocols::Serial::SerialChannel> _serial;
    std::unique_ptr<PocoDDS::Protocols::XBee::XBeePort> _port;
    std::atomic_bool _running{false};
    mutable Poco::FastMutex _mutex;
    Poco::Thread _thread;
    bool _ready{false};
    double _value{0};
    std::uint64_t _sequence{0};
    SnapshotHandler _snapshotHandler;
    ValueHandler _valueHandler;
};

} // namespace PocoDDS::Devices
