#include "PocoDDS/Protocols/CAN/CanEndpoint.h"
#include "PocoDDS/Protocols/Modbus/ModbusTcpClient.h"
#include "PocoDDS/Protocols/Modbus/ModbusTcpCodec.h"
#include "PocoDDS/Protocols/UDP/UdpChannel.h"

#include "Poco/Net/ServerSocket.h"
#include "Poco/Net/StreamSocket.h"
#include "Poco/Timespan.h"

#include <array>
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <thread>
#include <vector>

int main()
{
    using PocoDDS::Protocols::Modbus::FunctionCode;
    using PocoDDS::Protocols::Modbus::ModbusTcpCodec;

    const std::vector<std::uint8_t> expectedRequest{
        0x12, 0x34, 0x00, 0x00, 0x00, 0x06, 0x01, 0x03, 0x00, 0x10, 0x00, 0x02};
    const auto request =
        ModbusTcpCodec::readRegisters(0x1234, 1, FunctionCode::readHoldingRegisters, 0x10, 2);
    if (request != expectedRequest)
    {
        std::cerr << "PROTOCOL_SMOKE_FAIL invalid Modbus request\n";
        return 2;
    }

    const std::array<std::uint8_t, 13> responseBytes{
        0x12, 0x34, 0x00, 0x00, 0x00, 0x07, 0x01, 0x03, 0x04, 0x00, 0x2A, 0x01, 0x02};
    const auto response =
        ModbusTcpCodec::decodeResponse(responseBytes.data(), responseBytes.size());
    if (response.transactionId != 0x1234 || response.unitId != 1 || response.exception ||
        response.data != std::vector<std::uint8_t>({0x04, 0x00, 0x2A, 0x01, 0x02}))
    {
        std::cerr << "PROTOCOL_SMOKE_FAIL invalid Modbus response\n";
        return 3;
    }

    PocoDDS::Protocols::CAN::CanFrame frame;
    frame.id = 0x18FF50E5;
    frame.extended = true;
    frame.length = 8;
    frame.data[0] = 0xA5;
    if (!frame.extended || frame.length != 8 || frame.data[0] != 0xA5)
    {
        std::cerr << "PROTOCOL_SMOKE_FAIL invalid CAN model\n";
        return 4;
    }

    Poco::Net::ServerSocket server(Poco::Net::SocketAddress("127.0.0.1", 0));
    std::thread modbusServer([&] {
        auto socket = server.acceptConnection();
        std::array<std::uint8_t, 12> wireRequest{};
        std::size_t offset = 0;
        while (offset < wireRequest.size())
        {
            const int received = socket.receiveBytes(
                wireRequest.data() + offset, static_cast<int>(wireRequest.size() - offset));
            if (received <= 0)
                return;
            offset += static_cast<std::size_t>(received);
        }
        const std::array<std::uint8_t, 13> wireResponse{
            wireRequest[0], wireRequest[1], 0x00, 0x00, 0x00, 0x07, wireRequest[6],
            0x03, 0x04, 0x00, 0x2A, 0x01, 0x02};
        socket.sendBytes(wireResponse.data(), static_cast<int>(wireResponse.size()));
    });

    PocoDDS::Protocols::Modbus::ModbusTcpClient client(
        server.address(), Poco::Timespan(2, 0));
    client.open();
    const auto registerValues = client.readHoldingRegisters(1, 0x10, 2);
    client.close();
    modbusServer.join();
    if (registerValues != std::vector<std::uint16_t>({0x002A, 0x0102}))
    {
        std::cerr << "PROTOCOL_SMOKE_FAIL Modbus TCP loopback\n";
        return 5;
    }

    using PocoDDS::Protocols::UDP::UdpChannel;
    UdpChannel receiver(Poco::Net::SocketAddress("127.0.0.1", 0),
                        Poco::Net::SocketAddress("127.0.0.1", 9));
    receiver.open();
    UdpChannel sender(Poco::Net::SocketAddress("127.0.0.1", 0), receiver.localAddress());
    sender.open();
    const std::array<std::uint8_t, 4> datagram{0x50, 0x44, 0x52, 0x01};
    sender.send(datagram.data(), datagram.size());
    const auto received = receiver.receive(64, Poco::Timespan(2, 0));
    sender.close();
    receiver.close();
    if (received.size() != datagram.size() ||
        !std::equal(datagram.begin(), datagram.end(), received.begin()))
    {
        std::cerr << "PROTOCOL_SMOKE_FAIL UDP loopback\n";
        return 6;
    }

    std::cout << "PROTOCOL_SMOKE_PASS modbus-codec=1 modbus-tcp=1 can=1 udp=1\n";
    return 0;
}
