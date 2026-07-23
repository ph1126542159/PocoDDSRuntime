#include "PocoDDS/Protocols/UDP/UdpChannel.h"

#include <stdexcept>

namespace PocoDDS::Protocols::UDP
{
UdpChannel::UdpChannel(Poco::Net::SocketAddress local, Poco::Net::SocketAddress remote)
    : _local(std::move(local)), _remote(std::move(remote))
{
}

std::string UdpChannel::name() const
{
    return "udp";
}

void UdpChannel::open()
{
    if (_open)
        return;
    _socket = Poco::Net::DatagramSocket(_local.family());
    _socket.bind(_local);
    _open = true;
}

void UdpChannel::close() noexcept
{
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
    return _open;
}

std::size_t UdpChannel::send(const std::uint8_t* data, std::size_t size)
{
    if (!_open)
        throw std::logic_error("UDP channel is not open");
    return static_cast<std::size_t>(
        _socket.sendTo(data, static_cast<int>(size), _remote));
}

std::vector<std::uint8_t> UdpChannel::receive(std::size_t capacity, Poco::Timespan timeout)
{
    if (!_open)
        throw std::logic_error("UDP channel is not open");
    if (!_socket.poll(timeout, Poco::Net::Socket::SELECT_READ))
        return {};

    std::vector<std::uint8_t> bytes(capacity);
    Poco::Net::SocketAddress sender;
    const int received =
        _socket.receiveFrom(bytes.data(), static_cast<int>(bytes.size()), sender);
    bytes.resize(static_cast<std::size_t>(received));
    return bytes;
}

Poco::Net::SocketAddress UdpChannel::localAddress() const
{
    if (!_open)
        throw std::logic_error("UDP channel is not open");
    return _socket.address();
}
} // namespace PocoDDS::Protocols::UDP
