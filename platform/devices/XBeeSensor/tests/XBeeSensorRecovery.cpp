#include "PocoDDS/Devices/XBeeAnalogSensor.h"

#include <Poco/Thread.h>

#include <atomic>
#include <deque>
#include <functional>
#include <mutex>
#include <stdexcept>

namespace
{
class FlakySerialChannel final : public PocoDDS::Protocols::Serial::ISerialChannel
{
public:
    std::string name() const override { return "flaky-xbee"; }
    void open() override { _open = true; ++openCount; }
    void close() noexcept override { _open = false; }
    bool isOpen() const noexcept override { return _open; }
    std::size_t write(const std::uint8_t*, std::size_t size) override { return size; }
    std::vector<std::uint8_t> read(std::size_t size, Poco::Timespan) override
    {
        if (_fail.exchange(false)) throw std::runtime_error("XBee link lost");
        std::lock_guard<std::mutex> lock(_mutex);
        std::vector<std::uint8_t> result;
        while (!_bytes.empty() && result.size() < size)
        {
            result.push_back(_bytes.front());
            _bytes.pop_front();
        }
        if (result.empty()) Poco::Thread::sleep(5);
        return result;
    }
    void inject(const std::vector<std::uint8_t>& bytes)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _bytes.insert(_bytes.end(), bytes.begin(), bytes.end());
    }
    void failNext() { _fail = true; }
    std::atomic_int openCount{0};
private:
    std::atomic_bool _open{false};
    std::atomic_bool _fail{false};
    std::mutex _mutex;
    std::deque<std::uint8_t> _bytes;
};

bool waitFor(const std::function<bool()>& predicate, int timeoutMilliseconds)
{
    for (int elapsed = 0; elapsed < timeoutMilliseconds; elapsed += 10)
    {
        if (predicate()) return true;
        Poco::Thread::sleep(10);
    }
    return predicate();
}

PocoDDS::Protocols::XBee::XBeeFrame sampleFrame(std::uint64_t address)
{
    std::vector<std::uint8_t> data;
    for (int shift = 56; shift >= 0; shift -= 8)
        data.push_back(static_cast<std::uint8_t>(address >> shift));
    const std::vector<std::uint8_t> tail{
        0x7D, 0x84, 0x01, 0x01, 0x00, 0x00, 0x01, 0x02, 0x00};
    data.insert(data.end(), tail.begin(), tail.end());
    return {PocoDDS::Protocols::XBee::FrameType::zigbeeIoSample, std::move(data)};
}
}

int main()
{
    constexpr std::uint64_t address = 0x0013A200405291ABULL;
    auto channel = std::make_shared<FlakySerialChannel>();
    PocoDDS::Devices::XBeeAnalogSensor::Options options;
    options.id = "xbee-recovery";
    options.sourceAddress = address;
    options.analogChannel = 0;
    options.escapedApiMode = true;
    PocoDDS::Devices::XBeeRecoveryPolicy policy;
    policy.reconnectDelay = std::chrono::milliseconds(10);
    policy.receiveTimeout = std::chrono::milliseconds(10);
    policy.staleAfter = std::chrono::milliseconds(500);
    PocoDDS::Devices::XBeeAnalogSensor sensor(options, channel, policy);
    sensor.setValueHandler([](double) { throw std::runtime_error("consumer failure"); });
    sensor.start();
    if (sensor.snapshot().state != PocoDDS::Devices::DeviceState::offline) return 1;

    channel->inject(sampleFrame(1).encode(true));
    Poco::Thread::sleep(50);
    if (sensor.snapshot().state != PocoDDS::Devices::DeviceState::offline) return 2;
    if (sensor.diagnostics().successfulOperations != 0) return 3;

    channel->inject(sampleFrame(address).encode(true));
    if (!waitFor([&] {
            return sensor.snapshot().state == PocoDDS::Devices::DeviceState::ready;
        }, 500)) return 4;
    if (sensor.diagnostics().successfulOperations != 1) return 5;

    auto corrupt = sampleFrame(address).encode(true);
    corrupt.back() ^= 0x01;
    channel->inject(corrupt);
    if (!waitFor([&] {
            return sensor.diagnostics().failedOperations >= 1 &&
                sensor.diagnostics().reconnectAttempts >= 1 && channel->openCount >= 2;
        }, 500)) return 6;
    if (sensor.snapshot().state != PocoDDS::Devices::DeviceState::offline) return 7;

    channel->inject(sampleFrame(address).encode(true));
    if (!waitFor([&] {
            return sensor.snapshot().state == PocoDDS::Devices::DeviceState::ready;
        }, 500)) return 8;
    if (!waitFor([&] {
            return sensor.snapshot().state == PocoDDS::Devices::DeviceState::offline;
        }, 1500)) return 9;
    const auto stale = sensor.diagnostics();
    const auto failure = sensor.failure();
    if (stale.lastError != "XBee sample stale" ||
        failure.code != "PDR-DEVICE-XBEE-OPERATION_FAILED" ||
        !failure.active || !failure.retryable) return 10;
    sensor.stop();
    return 0;
}
