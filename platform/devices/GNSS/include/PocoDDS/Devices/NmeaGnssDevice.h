#pragma once

#include "PocoDDS/Devices/GNSSSensor.h"
#include "PocoDDS/Protocols/Serial/SerialChannel.h"

#include <Poco/Mutex.h>
#include <Poco/Thread.h>

#include <atomic>
#include <chrono>
#include <memory>
#include <string>

namespace PocoDDS::Devices
{

struct GnssRecoveryPolicy
{
    bool enabled{true};
    std::chrono::milliseconds reconnectDelay{250};
    std::chrono::milliseconds readTimeout{250};
    std::chrono::milliseconds staleAfter{5000};
};

class NmeaGnssDevice final : public GNSSSensor, public DiagnosticDevice,
                             public FailureDiagnosticDevice
{
public:
    NmeaGnssDevice(std::string id, std::string port, int baudRate = 9600,
                   GnssRecoveryPolicy recoveryPolicy = {});
    NmeaGnssDevice(
        std::string id,
        std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> channel,
        GnssRecoveryPolicy recoveryPolicy = {});
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
    DeviceDiagnostics diagnostics() const override;
    PocoDDS::Reliability::Failure failure() const override;

    bool ingestSentence(const std::string& sentence);

private:
    void run();
    void markConnected();
    void markFailure(const std::string& message, DeviceState state);
    void checkStale();
    void notify(const DeviceSnapshot& snapshot, const GeoPosition* position = nullptr);
    static bool validChecksum(const std::string& sentence);
    static double coordinate(const std::string& value, const std::string& hemisphere);

    std::string _id;
    std::string _type{"gnss.nmea0183"};
    std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> _channel;
    GnssRecoveryPolicy _recoveryPolicy;
    std::atomic_bool _running{false};
    mutable Poco::FastMutex _mutex;
    Poco::Thread _thread;
    std::string _buffer;
    GeoPosition _position;
    bool _hasFix{false};
    DeviceState _state{DeviceState::offline};
    std::chrono::steady_clock::time_point _lastFix;
    std::uint64_t _sequence{0};
    DeviceDiagnostics _diagnostics;
    PocoDDS::Reliability::Failure _failure;
    SnapshotHandler _snapshotHandler;
    PositionHandler _positionHandler;
};

} // namespace PocoDDS::Devices
