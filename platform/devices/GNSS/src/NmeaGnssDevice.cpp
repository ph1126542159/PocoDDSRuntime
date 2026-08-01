#include "PocoDDS/Devices/NmeaGnssDevice.h"

#include <Poco/NumberFormatter.h>
#include <Poco/StringTokenizer.h>
#include <Poco/Timestamp.h>

#include <cmath>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Devices
{

NmeaGnssDevice::NmeaGnssDevice(std::string id, std::string port, int baudRate,
                               GnssRecoveryPolicy recoveryPolicy)
    : NmeaGnssDevice(
          std::move(id),
          std::make_shared<PocoDDS::Protocols::Serial::SerialChannel>(
              std::move(port), baudRate),
          recoveryPolicy)
{
}

NmeaGnssDevice::NmeaGnssDevice(
    std::string id,
    std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> channel,
    GnssRecoveryPolicy recoveryPolicy)
    : _id(std::move(id)), _channel(std::move(channel)),
      _recoveryPolicy(recoveryPolicy)
{
    if (_id.empty()) throw std::invalid_argument("GNSS device id must not be empty");
    if (!_channel) throw std::invalid_argument("GNSS serial channel is required");
    if (_recoveryPolicy.reconnectDelay.count() < 0 ||
        _recoveryPolicy.readTimeout.count() <= 0 ||
        _recoveryPolicy.staleAfter.count() <= 0)
        throw std::invalid_argument("GNSS recovery timeouts are invalid");
}

NmeaGnssDevice::NmeaGnssDevice(std::string id): _id(std::move(id))
{
}

NmeaGnssDevice::~NmeaGnssDevice() { stop(); }
const std::string& NmeaGnssDevice::id() const noexcept { return _id; }
const std::string& NmeaGnssDevice::type() const noexcept { return _type; }

void NmeaGnssDevice::start()
{
    if (!_channel)
        throw std::logic_error("NMEA GNSS device has no serial channel");
    if (_running.exchange(true))
        return;
    try
    {
        _channel->open();
        markConnected();
        _thread.startFunc([this] { run(); });
        notify(snapshot());
    }
    catch (...)
    {
        _running = false;
        _channel->close();
        throw;
    }
}

void NmeaGnssDevice::stop() noexcept
{
    if (!_running.exchange(false))
        return;
    try { _thread.join(); } catch (...) {}
    if (_channel) _channel->close();
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        _state = DeviceState::offline;
        _hasFix = false;
        ++_sequence;
    }
    notify(snapshot());
}

DeviceSnapshot NmeaGnssDevice::snapshot() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    std::ostringstream value;
    if (_hasFix)
        value << _position.latitude << ',' << _position.longitude << ','
              << _position.altitude;
    else
        value << "no-fix";
    return {_id, _type, _state, _sequence,
            Poco::Timestamp().epochMicroseconds(), value.str()};
}

std::string NmeaGnssDevice::execute(const std::string& operation, const std::string&)
{
    if (operation == "position")
        return snapshot().payload;
    if (operation == "hasFix")
        return hasFix() ? "true" : "false";
    throw std::invalid_argument("unsupported GNSS operation: " + operation);
}

void NmeaGnssDevice::setSnapshotHandler(SnapshotHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _snapshotHandler = std::move(handler);
}

GeoPosition NmeaGnssDevice::position() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _position;
}

bool NmeaGnssDevice::hasFix() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _hasFix;
}

void NmeaGnssDevice::setPositionHandler(PositionHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _positionHandler = std::move(handler);
}

bool NmeaGnssDevice::validChecksum(const std::string& sentence)
{
    const auto star = sentence.find('*');
    if (sentence.empty() || sentence.front() != '$' || star == std::string::npos ||
        star + 2 >= sentence.size())
        return false;
    unsigned checksum = 0;
    for (std::size_t i = 1; i < star; ++i)
        checksum ^= static_cast<unsigned char>(sentence[i]);
    unsigned expected = 0;
    std::istringstream hex(sentence.substr(star + 1, 2));
    hex >> std::hex >> expected;
    return !hex.fail() && checksum == expected;
}

double NmeaGnssDevice::coordinate(const std::string& value, const std::string& hemisphere)
{
    if (value.empty())
        return 0;
    const double raw = std::stod(value);
    const double degrees = std::floor(raw / 100.0);
    double result = degrees + (raw - degrees * 100.0) / 60.0;
    if (hemisphere == "S" || hemisphere == "W")
        result = -result;
    return result;
}

bool NmeaGnssDevice::ingestSentence(const std::string& sentence)
{
    if (!validChecksum(sentence))
    {
        DeviceState state;
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            state = _state;
        }
        markFailure("invalid NMEA checksum", state);
        return false;
    }

    const auto star = sentence.find('*');
    // Empty NMEA fields are significant, so parse without dropping them.
    std::vector<std::string> values;
    std::size_t begin = 1;
    while (begin <= star)
    {
        const auto comma = sentence.find(',', begin);
        const auto end = comma == std::string::npos || comma > star ? star : comma;
        values.emplace_back(sentence.substr(begin, end - begin));
        if (end == star) break;
        begin = end + 1;
    }
    if (values.empty())
        return false;

    GeoPosition updated;
    bool positionUpdate = false;
    bool recognized = false;
    try
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        updated = _position;
        const auto& kind = values[0];
        if ((kind == "GPRMC" || kind == "GNRMC") && values.size() >= 10)
        {
            recognized = true;
            _hasFix = values[2] == "A";
            if (_hasFix)
            {
                updated.latitude = coordinate(values[3], values[4]);
                updated.longitude = coordinate(values[5], values[6]);
                updated.speed = values[7].empty() ? 0 : std::stod(values[7]);
                updated.course = values[8].empty() ? 0 : std::stod(values[8]);
                positionUpdate = true;
            }
        }
        else if ((kind == "GPGGA" || kind == "GNGGA") && values.size() >= 10)
        {
            recognized = true;
            _hasFix = !values[6].empty() && values[6] != "0";
            if (_hasFix)
            {
                updated.latitude = coordinate(values[2], values[3]);
                updated.longitude = coordinate(values[4], values[5]);
                updated.altitude = values[9].empty() ? 0 : std::stod(values[9]);
                positionUpdate = true;
            }
        }
        else return false;

        updated.timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
        _position = updated;
        _state = _hasFix ? DeviceState::ready : DeviceState::offline;
        if (_hasFix)
        {
            _lastFix = std::chrono::steady_clock::now();
            ++_diagnostics.successfulOperations;
            _diagnostics.consecutiveFailures = 0;
            _diagnostics.lastSuccessMicroseconds = updated.timestampMicroseconds;
            _diagnostics.lastError.clear();
        }
        else
        {
            ++_diagnostics.failedOperations;
            ++_diagnostics.consecutiveFailures;
            _diagnostics.lastFailureMicroseconds = updated.timestampMicroseconds;
            _diagnostics.lastError = "GNSS fix invalid";
        }
        ++_sequence;
    }
    catch (const std::exception& error)
    {
        DeviceState state;
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            state = _state;
        }
        markFailure(std::string("invalid NMEA fields: ") + error.what(), state);
        return false;
    }

    notify(snapshot(), positionUpdate ? &updated : nullptr);
    return recognized;
}

void NmeaGnssDevice::run()
{
    while (_running)
    {
        if (!_channel->isOpen())
        {
            if (!_recoveryPolicy.enabled) break;
            {
                Poco::FastMutex::ScopedLock lock(_mutex);
                ++_diagnostics.reconnectAttempts;
            }
            try
            {
                _channel->open();
                markConnected();
                notify(snapshot());
            }
            catch (const std::exception& error)
            {
                markFailure(error.what(), DeviceState::fault);
                notify(snapshot());
                Poco::Thread::sleep(static_cast<long>(_recoveryPolicy.reconnectDelay.count()));
            }
            continue;
        }
        try
        {
            const auto timeout = static_cast<Poco::Timespan::TimeDiff>(
                _recoveryPolicy.readTimeout.count()) * Poco::Timespan::MILLISECONDS;
            const auto bytes = _channel->read(1024, Poco::Timespan(timeout));
            if (bytes.empty())
            {
                checkStale();
                continue;
            }
            _buffer.append(bytes.begin(), bytes.end());
            std::size_t newline = 0;
            while ((newline = _buffer.find_first_of("\r\n")) != std::string::npos)
            {
                const auto line = _buffer.substr(0, newline);
                const auto next = _buffer.find_first_not_of("\r\n", newline);
                _buffer.erase(0, next == std::string::npos ? _buffer.size() : next);
                if (!line.empty()) ingestSentence(line);
            }
            checkStale();
        }
        catch (const std::exception& error)
        {
            _channel->close();
            markFailure(error.what(), DeviceState::fault);
            notify(snapshot());
            if (_recoveryPolicy.enabled)
                Poco::Thread::sleep(static_cast<long>(_recoveryPolicy.reconnectDelay.count()));
        }
    }
}

void NmeaGnssDevice::markConnected()
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = DeviceState::offline;
    _hasFix = false;
    _buffer.clear();
    ++_sequence;
}

void NmeaGnssDevice::markFailure(const std::string& message, DeviceState state)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = state;
    if (state != DeviceState::ready) _hasFix = false;
    ++_sequence;
    ++_diagnostics.failedOperations;
    ++_diagnostics.consecutiveFailures;
    _diagnostics.lastFailureMicroseconds = Poco::Timestamp().epochMicroseconds();
    _diagnostics.lastError = message;
}

void NmeaGnssDevice::checkStale()
{
    bool stale = false;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        stale = _state == DeviceState::ready && _lastFix.time_since_epoch().count() != 0 &&
            std::chrono::steady_clock::now() - _lastFix >= _recoveryPolicy.staleAfter;
    }
    if (stale)
    {
        markFailure("GNSS fix stale", DeviceState::offline);
        notify(snapshot());
    }
}

void NmeaGnssDevice::notify(const DeviceSnapshot& current, const GeoPosition* position)
{
    SnapshotHandler snapshotHandler;
    PositionHandler positionHandler;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        snapshotHandler = _snapshotHandler;
        positionHandler = _positionHandler;
    }
    if (position && positionHandler) try { positionHandler(*position); } catch (...) {}
    if (snapshotHandler) try { snapshotHandler(current); } catch (...) {}
}

DeviceDiagnostics NmeaGnssDevice::diagnostics() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _diagnostics;
}

} // namespace PocoDDS::Devices
