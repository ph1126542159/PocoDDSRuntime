#pragma once

#include "PocoDDS/Devices/Sensor.h"
#include "PocoDDS/Protocols/CAN/SignalCodec.h"
#include "PocoDDS/Protocols/CAN/SocketCanEndpoint.h"

#include <Poco/Mutex.h>
#include <Poco/Thread.h>

#include <atomic>
#include <memory>
#include <string>

namespace PocoDDS::Devices
{
class CanSignalSensor final : public Sensor
{
public:
    struct Options
    {
        std::string id;
        std::string interfaceName;
        std::uint32_t frameId{0};
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

    explicit CanSignalSensor(Options options);
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

private:
    void run();
    Options _options;
    std::string _type{"sensor.can.signal"};
    std::unique_ptr<PocoDDS::Protocols::CAN::SocketCanEndpoint> _endpoint;
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
