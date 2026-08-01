#include "PocoDDS/Protocols/UDP/UdpChannel.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <stdexcept>
#include <limits>

namespace PocoDDS::Protocols::UDP
{
UdpChannel::UdpChannel(Options options)
    : _local(std::move(options.local)), _remote(std::move(options.remote))
{
}

UdpChannel::UdpChannel(Poco::Net::SocketAddress local, Poco::Net::SocketAddress remote)
    : UdpChannel(Options{std::move(local), std::move(remote)})
{
}

std::string UdpChannel::name() const
{
    return "udp";
}

void UdpChannel::open()
{
    std::lock_guard lock(_mutex);
    if (_open)
        return;
    PocoDDS::Protocols::ProtocolMetricTimer metric("udp", "open");
    try
    {
        _socket = Poco::Net::DatagramSocket(_local.family());
        _socket.bind(_local);
        _open = true;
        ++_diagnostics.successfulOperations;
        _diagnostics.lastError.clear();
        metric.success();
    }
    catch (const std::exception& error)
    {
        ++_diagnostics.failedOperations;
        _diagnostics.lastError = error.what();
        throw;
    }
}

void UdpChannel::close() noexcept
{
    std::lock_guard lock(_mutex);
    if (!_open)
        return;
    try
    {
        _socket.close();
    }
    catch (...)
    {
    }
    _open = false;
}

bool UdpChannel::isOpen() const noexcept
{
    std::lock_guard lock(_mutex);
    return _open;
}

std::size_t UdpChannel::send(const std::uint8_t* data, std::size_t size)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("udp", "send", size);
    if (size > static_cast<std::size_t>(std::numeric_limits<int>::max()))
        throw std::length_error("UDP payload exceeds socket API limit");
    if (size > 0 && !data)
        throw std::invalid_argument("UDP payload pointer is null");
    std::lock_guard lock(_mutex);
    try
    {
        if (!_open)
            throw std::logic_error("UDP channel is not open");
        const auto sent = static_cast<std::size_t>(
            _socket.sendTo(data, static_cast<int>(size), _remote));
        ++_diagnostics.successfulOperations;
        ++_diagnostics.sentMessages;
        _diagnostics.sentBytes += sent;
        _diagnostics.lastError.clear();
        metric.success();
        return sent;
    }
    catch (const std::exception& error)
    {
        ++_diagnostics.failedOperations;
        _diagnostics.lastError = error.what();
        throw;
    }
}

std::vector<std::uint8_t> UdpChannel::receive(std::size_t capacity, Poco::Timespan timeout)
{
    return receiveDatagram(capacity, timeout).bytes;
}

Datagram UdpChannel::receiveDatagram(std::size_t capacity, Poco::Timespan timeout)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("udp", "receive");
    if (capacity == 0 || capacity > static_cast<std::size_t>(std::numeric_limits<int>::max()))
        throw std::length_error("UDP receive capacity must be in socket API range");
    if (timeout.totalMicroseconds() < 0)
        throw std::invalid_argument("UDP receive timeout must be non-negative");
    std::lock_guard lock(_mutex);
    try
    {
        if (!_open)
            throw std::logic_error("UDP channel is not open");
        if (!_socket.poll(timeout, Poco::Net::Socket::SELECT_READ))
        {
            ++_diagnostics.timeouts;
            metric.timeout();
            return {};
        }

        Datagram datagram;
        datagram.bytes.resize(capacity);
        const int received =
            _socket.receiveFrom(datagram.bytes.data(), static_cast<int>(datagram.bytes.size()),
                                datagram.sender);
        if (received < 0)
            throw std::runtime_error("UDP receive returned a negative byte count");
        datagram.bytes.resize(static_cast<std::size_t>(received));
        datagram.received = true;
        ++_diagnostics.successfulOperations;
        ++_diagnostics.receivedMessages;
        _diagnostics.receivedBytes += static_cast<std::size_t>(received);
        _diagnostics.lastError.clear();
        metric.success();
        return datagram;
    }
    catch (const std::exception& error)
    {
        ++_diagnostics.failedOperations;
        _diagnostics.lastError = error.what();
        throw;
    }
}

Poco::Net::SocketAddress UdpChannel::localAddress() const
{
    std::lock_guard lock(_mutex);
    if (!_open)
        throw std::logic_error("UDP channel is not open");
    return _socket.address();
}

ProtocolDiagnostics UdpChannel::diagnostics() const
{
    std::lock_guard lock(_mutex);
    return _diagnostics;
}
} // namespace PocoDDS::Protocols::UDP
