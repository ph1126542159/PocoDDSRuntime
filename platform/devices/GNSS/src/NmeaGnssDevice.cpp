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

NmeaGnssDevice::NmeaGnssDevice(std::string id, std::string port, int baudRate)
    : _id(std::move(id)),
      _channel(std::make_unique<PocoDDS::Protocols::Serial::SerialChannel>(
          std::move(port), baudRate))
{
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
        _thread.startFunc([this] { run(); });
    }
    catch (...)
    {
        _running = false;
        throw;
    }
}

void NmeaGnssDevice::stop() noexcept
{
    if (!_running.exchange(false))
        return;
    try { _thread.join(); } catch (...) {}
    if (_channel) _channel->close();
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
    return {_id, _type, _hasFix ? DeviceState::ready : DeviceState::offline, _sequence,
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
        return false;

    const auto star = sentence.find('*');
    Poco::StringTokenizer fields(
        sentence.substr(1, star - 1), ",",
        Poco::StringTokenizer::TOK_TRIM | Poco::StringTokenizer::TOK_IGNORE_EMPTY);

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
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        updated = _position;
        const auto& kind = values[0];
        if ((kind == "GPRMC" || kind == "GNRMC") && values.size() >= 10)
        {
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
            _hasFix = !values[6].empty() && values[6] != "0";
            if (_hasFix)
            {
                updated.latitude = coordinate(values[2], values[3]);
                updated.longitude = coordinate(values[4], values[5]);
                updated.altitude = values[9].empty() ? 0 : std::stod(values[9]);
                positionUpdate = true;
            }
        }
        else
        {
            return false;
        }

        updated.timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
        _position = updated;
        ++_sequence;
    }

    PositionHandler positionHandler;
    SnapshotHandler snapshotHandler;
    if (positionUpdate)
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        positionHandler = _positionHandler;
        snapshotHandler = _snapshotHandler;
    }
    if (positionHandler) positionHandler(updated);
    if (snapshotHandler) snapshotHandler(snapshot());
    return true;
}

void NmeaGnssDevice::run()
{
    while (_running)
    {
        const auto bytes = _channel->read(1024, Poco::Timespan(0, 250000));
        if (bytes.empty())
            continue;
        _buffer.append(bytes.begin(), bytes.end());
        std::size_t newline = 0;
        while ((newline = _buffer.find_first_of("\r\n")) != std::string::npos)
        {
            const auto line = _buffer.substr(0, newline);
            _buffer.erase(0, _buffer.find_first_not_of("\r\n", newline));
            if (!line.empty())
                ingestSentence(line);
        }
    }
}

} // namespace PocoDDS::Devices
