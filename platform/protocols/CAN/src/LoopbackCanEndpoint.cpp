#include "PocoDDS/Protocols/CAN/LoopbackCanEndpoint.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <stdexcept>
#include <utility>

namespace PocoDDS::Protocols::CAN
{
LoopbackCanEndpoint::LoopbackCanEndpoint(std::string endpointName)
    : _name(std::move(endpointName))
{
    if (_name.empty())
        throw std::invalid_argument("loopback CAN endpoint name must not be empty");
}

std::string LoopbackCanEndpoint::name() const { return "can-loopback:" + _name; }

void LoopbackCanEndpoint::open()
{
    std::lock_guard lock(_mutex);
    _open = true;
}

void LoopbackCanEndpoint::close() noexcept
{
    {
        std::lock_guard lock(_mutex);
        _open = false;
        _frames.clear();
    }
    _ready.notify_all();
}

bool LoopbackCanEndpoint::isOpen() const noexcept
{
    std::lock_guard lock(_mutex);
    return _open;
}

void LoopbackCanEndpoint::send(const CanFrame& frame)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("can-loopback", "send", frame.length);
    if (frame.length > frame.data.size())
        throw std::out_of_range("CAN frame payload exceeds 64 bytes");
    if (!frame.error && ((!frame.extended && frame.id > 0x7FFU) ||
                         (frame.extended && frame.id > 0x1FFFFFFFU)))
        throw std::out_of_range("CAN frame identifier exceeds selected format");
    {
        std::lock_guard lock(_mutex);
        if (!_open)
            throw std::logic_error("loopback CAN endpoint is not open");
        _frames.push_back(frame);
    }
    _ready.notify_one();
    metric.success();
}

bool LoopbackCanEndpoint::receive(CanFrame& frame, std::chrono::milliseconds timeout)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("can-loopback", "receive");
    FrameHandler handler;
    {
        std::unique_lock lock(_mutex);
        if (!_open)
            throw std::logic_error("loopback CAN endpoint is not open");
        if (!_ready.wait_for(lock, timeout, [&] { return !_frames.empty() || !_open; }))
        {
            metric.timeout();
            return false;
        }
        if (!_open)
            throw std::runtime_error("loopback CAN endpoint disconnected");
        frame = _frames.front();
        _frames.pop_front();
        handler = _handler;
    }
    if (handler)
    {
        try { handler(frame); } catch (...) {}
    }
    metric.success();
    return true;
}

void LoopbackCanEndpoint::setFrameHandler(FrameHandler handler)
{
    std::lock_guard lock(_mutex);
    _handler = std::move(handler);
}

void LoopbackCanEndpoint::injectError(std::uint32_t errorMask)
{
    CanFrame frame;
    frame.id = errorMask;
    frame.error = true;
    send(frame);
}

void LoopbackCanEndpoint::disconnect() { close(); }
}
