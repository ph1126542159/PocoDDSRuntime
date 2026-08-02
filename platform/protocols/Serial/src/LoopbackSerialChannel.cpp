#include "PocoDDS/Protocols/Serial/LoopbackSerialChannel.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <algorithm>
#include <chrono>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Protocols::Serial
{
LoopbackSerialChannel::LoopbackSerialChannel(std::string channelName)
    : _name(std::move(channelName))
{
    if (_name.empty())
        throw std::invalid_argument("loopback serial channel name must not be empty");
}

std::string LoopbackSerialChannel::name() const { return "serial-loopback:" + _name; }

void LoopbackSerialChannel::open()
{
    std::lock_guard lock(_mutex);
    _open = true;
}

void LoopbackSerialChannel::close() noexcept
{
    {
        std::lock_guard lock(_mutex);
        _open = false;
        _bytes.clear();
    }
    _ready.notify_all();
}

bool LoopbackSerialChannel::isOpen() const noexcept
{
    std::lock_guard lock(_mutex);
    return _open;
}

std::size_t LoopbackSerialChannel::write(const std::uint8_t* data, std::size_t size)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("serial-loopback", "write", size);
    {
        std::lock_guard lock(_mutex);
        if (!_open)
            throw std::logic_error("loopback serial channel is not open");
        _bytes.insert(_bytes.end(), data, data + size);
    }
    _ready.notify_one();
    metric.success();
    return size;
}

std::vector<std::uint8_t> LoopbackSerialChannel::read(std::size_t size,
                                                       Poco::Timespan timeout)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("serial-loopback", "read");
    std::unique_lock lock(_mutex);
    if (!_open)
        throw std::logic_error("loopback serial channel is not open");
    const auto wait = std::chrono::microseconds(timeout.totalMicroseconds());
    if (!_ready.wait_for(lock, wait, [&] { return !_bytes.empty() || !_open; }))
    {
        metric.timeout();
        return {};
    }
    if (!_open)
        throw std::runtime_error("loopback serial channel closed while reading");
    const auto count = std::min(size, _bytes.size());
    std::vector<std::uint8_t> result;
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index)
    {
        result.push_back(_bytes.front());
        _bytes.pop_front();
    }
    metric.success();
    return result;
}
}
