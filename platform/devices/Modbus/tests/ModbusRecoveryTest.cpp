#include "PocoDDS/Devices/ModbusRegisterDevice.h"

#include "Poco/Net/ServerSocket.h"
#include "Poco/Net/SocketAddress.h"
#include "Poco/Timespan.h"

#include <array>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <memory>
#include <thread>

namespace
{
void receiveRequest(Poco::Net::StreamSocket& socket, std::array<std::uint8_t, 12>& request)
{
    std::size_t offset = 0;
    while (offset < request.size())
    {
        const int received = socket.receiveBytes(
            request.data() + offset, static_cast<int>(request.size() - offset));
        if (received <= 0)
            return;
        offset += static_cast<std::size_t>(received);
    }
}
}

int main()
{
    Poco::Net::ServerSocket server(Poco::Net::SocketAddress("127.0.0.1", 0));
    std::thread responder([&] {
        std::array<std::uint8_t, 12> request{};
        auto first = server.acceptConnection();
        receiveRequest(first, request);
        first.close();

        auto second = server.acceptConnection();
        receiveRequest(second, request);
        const std::array<std::uint8_t, 11> response{
            request[0], request[1], 0, 0, 0, 5, request[6], 3, 2, 0x12, 0x34};
        second.sendBytes(response.data(), static_cast<int>(response.size()));
        receiveRequest(second, request);
        second.close();
    });

    auto client = std::make_shared<PocoDDS::Protocols::Modbus::ModbusTcpClient>(
        server.address(), Poco::Timespan(0, 500000));
    PocoDDS::Devices::ModbusReconnectPolicy policy;
    policy.readRetryAttempts = 1;
    policy.retryDelay = std::chrono::milliseconds(1);
    PocoDDS::Devices::ModbusRegisterDevice device("modbus-recovery", client, 1, policy);
    int notifications = 0;
    device.setSnapshotHandler([&](const auto&) { ++notifications; });
    device.start();

    const auto value = device.execute("readHolding", "0,1");
    const auto recovered = device.snapshot();
    const auto recoveredDiagnostics = device.diagnostics();
    bool writeFailed = false;
    try
    {
        static_cast<void>(device.execute("writeRegister", "0,7"));
    }
    catch (...)
    {
        writeFailed = true;
    }
    const auto failed = device.snapshot();
    const auto diagnostics = device.diagnostics();
    const auto failure = device.failure();
    device.stop();
    responder.join();

    if (value != "4660" || recovered.state != PocoDDS::Devices::DeviceState::ready ||
        recoveredDiagnostics.successfulOperations != 1 ||
        recoveredDiagnostics.failedOperations != 1 ||
        recoveredDiagnostics.reconnectAttempts != 1 ||
        !writeFailed || failed.state != PocoDDS::Devices::DeviceState::fault ||
        diagnostics.successfulOperations != 1 || diagnostics.failedOperations != 2 ||
        diagnostics.reconnectAttempts != 1 || diagnostics.consecutiveFailures != 1 ||
        diagnostics.lastError.empty() ||
        failure.code != "PDR-DEVICE-MODBUS-OPERATION_FAILED" ||
        !failure.active || !failure.retryable || notifications < 4)
    {
        std::cerr << "MODBUS_DEVICE_RECOVERY_FAIL value=" << value
                  << " success=" << diagnostics.successfulOperations
                  << " failures=" << diagnostics.failedOperations
                  << " reconnects=" << diagnostics.reconnectAttempts
                  << " notifications=" << notifications << '\n';
        return 2;
    }
    std::cout << "MODBUS_DEVICE_RECOVERY_PASS read-retried=1 write-replayed=0\n";
    return 0;
}
