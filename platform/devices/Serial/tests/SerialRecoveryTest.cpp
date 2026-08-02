#include "PocoDDS/Devices/SerialPortDevice.h"

#include "Poco/Thread.h"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
class FakeSerialChannel final : public PocoDDS::Protocols::Serial::ISerialChannel
{
public:
    std::string name() const override { return "serial:fake"; }
    void open() override
    {
        ++openCount;
        openState = true;
    }
    void close() noexcept override
    {
        ++closeCount;
        openState = false;
    }
    bool isOpen() const noexcept override { return openState; }
    std::size_t write(const std::uint8_t*, std::size_t size) override
    {
        ++writeCount;
        if (failWrite)
        {
            openState = false;
            throw std::runtime_error("injected serial write disconnect");
        }
        return size;
    }
    std::vector<std::uint8_t> read(std::size_t, Poco::Timespan) override
    {
        ++readCount;
        if (readFailures.fetch_sub(1) > 0)
        {
            openState = false;
            throw std::runtime_error("injected serial read disconnect");
        }
        if (!dataDelivered.exchange(true))
            return {0x41, 0x42, 0x43};
        Poco::Thread::sleep(2);
        return {};
    }

    std::atomic_bool openState{false};
    std::atomic_bool failWrite{false};
    std::atomic_bool dataDelivered{false};
    std::atomic_int readFailures{1};
    std::atomic_uint openCount{0};
    std::atomic_uint closeCount{0};
    std::atomic_uint readCount{0};
    std::atomic_uint writeCount{0};
};
}

int main()
{
    using namespace std::chrono_literals;
    auto channel = std::make_shared<FakeSerialChannel>();
    PocoDDS::Devices::SerialReconnectPolicy policy;
    policy.delay = 1ms;
    policy.readTimeout = 5ms;
    PocoDDS::Devices::SerialPortDevice device("serial-recovery", channel, policy);
    std::atomic_uint dataNotifications{0};
    std::atomic_uint snapshotNotifications{0};
    device.setDataHandler([&](const auto& bytes) {
        if (bytes == std::vector<std::uint8_t>({0x41, 0x42, 0x43}))
            ++dataNotifications;
        throw std::runtime_error("injected consumer failure");
    });
    device.setSnapshotHandler([&](const auto&) { ++snapshotNotifications; });
    device.start();
    for (int wait = 0; wait < 200 && dataNotifications == 0; ++wait)
        Poco::Thread::sleep(2);
    const auto recovered = device.snapshot();
    const auto diagnostics = device.diagnostics();
    device.stop();
    if (dataNotifications != 1 || recovered.state != PocoDDS::Devices::DeviceState::ready ||
        diagnostics.failedOperations != 1 || diagnostics.successfulOperations != 1 ||
        diagnostics.reconnectAttempts != 1 || diagnostics.consecutiveFailures != 0 ||
        channel->openCount != 2 || snapshotNotifications < 3)
    {
        std::cerr << "SERIAL_RECOVERY_FAIL data=" << dataNotifications
                  << " success=" << diagnostics.successfulOperations
                  << " failures=" << diagnostics.failedOperations
                  << " reconnects=" << diagnostics.reconnectAttempts
                  << " opens=" << channel->openCount << '\n';
        return 2;
    }

    auto writeChannel = std::make_shared<FakeSerialChannel>();
    writeChannel->readFailures = 0;
    writeChannel->dataDelivered = true;
    PocoDDS::Devices::SerialReconnectPolicy noReplay;
    noReplay.enabled = false;
    noReplay.readTimeout = 5ms;
    PocoDDS::Devices::SerialPortDevice writer("serial-write", writeChannel, noReplay);
    writer.start();
    writeChannel->failWrite = true;
    bool failed = false;
    try
    {
        static_cast<void>(writer.execute("write", "command"));
    }
    catch (...)
    {
        failed = true;
    }
    Poco::Thread::sleep(10);
    const auto writeSnapshot = writer.snapshot();
    const auto writeDiagnostics = writer.diagnostics();
    const auto writeFailure = writer.failure();
    writer.stop();
    if (!failed || writeChannel->writeCount != 1 || writeChannel->openCount != 1 ||
        writeSnapshot.state != PocoDDS::Devices::DeviceState::fault ||
        writeDiagnostics.failedOperations == 0 ||
        writeFailure.code != "PDR-DEVICE-SERIAL-OPERATION_FAILED" ||
        !writeFailure.active || !writeFailure.retryable)
        return 3;

    std::cout << "SERIAL_RECOVERY_PASS read-reconnected=1 write-replayed=0\n";
    return 0;
}
