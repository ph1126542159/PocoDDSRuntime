#pragma once

#include "PocoDDS/Protocols/Protocol.h"

#include "Poco/Net/DatagramSocket.h"
#include "Poco/Net/SocketAddress.h"
#include "Poco/Timespan.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace PocoDDS::Protocols::UDP
{
class UdpChannel final : public PocoDDS::Protocols::Protocol
{
public:
    UdpChannel(Poco::Net::SocketAddress local, Poco::Net::SocketAddress remote);

    std::string name() const override;
    void open() override;
    void close() noexcept override;
    bool isOpen() const noexcept override;

    std::size_t send(const std::uint8_t* data, std::size_t size);
    std::vector<std::uint8_t> receive(std::size_t capacity, Poco::Timespan timeout);
    Poco::Net::SocketAddress localAddress() const;

private:
    Poco::Net::SocketAddress _local;
    Poco::Net::SocketAddress _remote;
    Poco::Net::DatagramSocket _socket;
    bool _open{false};
};
} // namespace PocoDDS::Protocols::UDP
