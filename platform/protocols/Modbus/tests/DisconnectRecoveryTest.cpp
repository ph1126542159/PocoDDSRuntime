#include "PocoDDS/Protocols/Modbus/ModbusTcpClient.h"

#include "Poco/Net/ServerSocket.h"
#include "Poco/Net/StreamSocket.h"
#include "Poco/Timespan.h"

#include <array>
#include <cstdint>
#include <iostream>
#include <thread>

namespace
{
void receiveRequest(Poco::Net::StreamSocket& socket, std::array<std::uint8_t, 12>& request)
{
    std::size_t offset = 0;
    while (offset < request.size())
    {
        const int received =
            socket.receiveBytes(request.data() + offset,
                                static_cast<int>(request.size() - offset));
        if (received <= 0)
            return;
        offset += static_cast<std::size_t>(received);
    }
}
}

int main()
{
    Poco::Net::ServerSocket server(Poco::Net::SocketAddress("127.0.0.1", 0));
    const auto address = server.address();
    std::thread peer([&] {
        std::array<std::uint8_t, 12> request{};
        {
            auto first = server.acceptConnection();
            receiveRequest(first, request);
            first.close(); // Inject a reset before the response.
        }
        {
            auto second = server.acceptConnection();
            receiveRequest(second, request);
            const std::array<std::uint8_t, 11> response{
                request[0], request[1], 0, 0, 0, 5, request[6], 3, 2, 0x12, 0x34};
            second.sendBytes(response.data(), static_cast<int>(response.size()));
        }
    });

    PocoDDS::Protocols::Modbus::ModbusTcpClient client(address, Poco::Timespan(0, 500000));
    client.open();
    bool disconnected = false;
    try
    {
        static_cast<void>(client.readHoldingRegisters(1, 0, 1));
    }
    catch (...)
    {
        disconnected = !client.isOpen();
    }
    if (client.isOpen())
        client.close();
    client.open();
    const auto values = client.readHoldingRegisters(1, 0, 1);
    peer.join();
    if (!disconnected)
        return 1;
    if (values.size() != 1 || values.front() != 0x1234 || !client.isOpen())
        return 2;
    std::cout << "MODBUS_DISCONNECT_RECOVERY_PASS value=0x1234\n";
    return 0;
}
