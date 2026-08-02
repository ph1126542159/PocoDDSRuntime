#pragma once

#include "PocoDDS/Protocols/Protocol.h"
#include "PocoDDS/Protocols/ProtocolDiagnostics.h"

#include "Poco/Net/DatagramSocket.h"
#include "Poco/Net/SocketAddress.h"
#include "Poco/Timespan.h"

#include <cstddef>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

namespace PocoDDS::Protocols::UDP
{
struct Datagram
{
    std::vector<std::uint8_t> bytes;
    Poco::Net::SocketAddress sender;
    bool received{false};
};

class UdpChannel final : public PocoDDS::Protocols::DiagnosticProtocol,
                         public PocoDDS::Protocols::FailureDiagnosticProtocol
{
public:
    struct Options
    {
        Poco::Net::SocketAddress local;
        Poco::Net::SocketAddress remote;
    };

    explicit UdpChannel(Options options);
    UdpChannel(Poco::Net::SocketAddress local, Poco::Net::SocketAddress remote);

    std::string name() const override;
    void open() override;
    void close() noexcept override;
    bool isOpen() const noexcept override;

    std::size_t send(const std::uint8_t* data, std::size_t size);
    std::vector<std::uint8_t> receive(std::size_t capacity, Poco::Timespan timeout);
    Datagram receiveDatagram(std::size_t capacity, Poco::Timespan timeout);
    Poco::Net::SocketAddress localAddress() const;
    ProtocolDiagnostics diagnostics() const override;
    PocoDDS::Reliability::Failure failure() const override;

private:
    Poco::Net::SocketAddress _local;
    Poco::Net::SocketAddress _remote;
    Poco::Net::DatagramSocket _socket;
    bool _open{false};
    ProtocolDiagnostics _diagnostics;
    PocoDDS::Reliability::Failure _failure;
    mutable std::mutex _mutex;
};
} // namespace PocoDDS::Protocols::UDP
