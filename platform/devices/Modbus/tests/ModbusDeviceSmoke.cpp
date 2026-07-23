#include "PocoDDS/Devices/ModbusRegisterDevice.h"

#include "Poco/Net/ServerSocket.h"
#include "Poco/Net/SocketAddress.h"

#include <array>
#include <cstdint>
#include <iostream>
#include <memory>
#include <thread>

int main()
{
    Poco::Net::ServerSocket server(Poco::Net::SocketAddress("127.0.0.1", 0));
    std::thread responder([&] {
        auto socket = server.acceptConnection();
        std::array<std::uint8_t, 12> request{};
        std::size_t offset = 0;
        while (offset < request.size())
        {
            const int received = socket.receiveBytes(
                request.data() + offset, static_cast<int>(request.size() - offset));
            if (received <= 0)
                return;
            offset += static_cast<std::size_t>(received);
        }
        const std::array<std::uint8_t, 13> response{
            request[0], request[1], 0, 0, 0, 7, request[6], 3, 4, 0, 100, 0, 200};
        socket.sendBytes(response.data(), static_cast<int>(response.size()));
    });

    auto client =
        std::make_shared<PocoDDS::Protocols::Modbus::ModbusTcpClient>(server.address());
    PocoDDS::Devices::ModbusRegisterDevice device("modbus-test", client, 1);
    int notifications = 0;
    device.setSnapshotHandler(
        [&](const PocoDDS::Devices::DeviceSnapshot&) { ++notifications; });
    device.start();
    const std::string result = device.execute("readHolding", "16,2");
    const auto snapshot = device.snapshot();
    device.stop();
    responder.join();

    if (result != "100,200" || snapshot.payload != result ||
        snapshot.state != PocoDDS::Devices::DeviceState::ready || notifications < 2)
    {
        std::cerr << "MODBUS_DEVICE_SMOKE_FAIL result=" << result
                  << " notifications=" << notifications << '\n';
        return 2;
    }
    std::cout << "MODBUS_DEVICE_SMOKE_PASS result=" << result
              << " notifications=" << notifications << '\n';
    return 0;
}
