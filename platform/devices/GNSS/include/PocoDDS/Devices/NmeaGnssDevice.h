#pragma once

#include "PocoDDS/Devices/GNSSSensor.h"
#include "PocoDDS/Protocols/Serial/SerialChannel.h"

#include <Poco/Mutex.h>
#include <Poco/Thread.h>

#include <atomic>
#include <memory>
#include <string>

namespace PocoDDS::Devices
{

class NmeaGnssDevice final : public GNSSSensor
{
public:
    NmeaGnssDevice(std::string id, std::string port, int baudRate = 9600);
    explicit NmeaGnssDevice(std::string id);
    ~NmeaGnssDevice() override;

    const std::string& id() const noexcept override;
    const std::string& type() const noexcept override;
    void start() override;
    void stop() noexcept override;
    DeviceSnapshot snapshot() const override;
    std::string execute(const std::string& operation, const std::string& payload) override;
    void setSnapshotHandler(SnapshotHandler handler) override;

    GeoPosition position() const override;
    bool hasFix() const override;
    void setPositionHandler(PositionHandler handler) override;

    bool ingestSentence(const std::string& sentence);

private:
    void run();
    static bool validChecksum(const std::string& sentence);
    static double coordinate(const std::string& value, const std::string& hemisphere);

    std::string _id;
    std::string _type{"gnss.nmea0183"};
    std::unique_ptr<PocoDDS::Protocols::Serial::SerialChannel> _channel;
    std::atomic_bool _running{false};
    mutable Poco::FastMutex _mutex;
    Poco::Thread _thread;
    std::string _buffer;
    GeoPosition _position;
    bool _hasFix{false};
    std::uint64_t _sequence{0};
    SnapshotHandler _snapshotHandler;
    PositionHandler _positionHandler;
};

} // namespace PocoDDS::Devices
