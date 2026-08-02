#include "PocoDDS/Devices/NmeaGnssDevice.h"

#include <Poco/Thread.h>

#include <atomic>
#include <deque>
#include <mutex>
#include <stdexcept>

namespace
{
class FlakySerialChannel final : public PocoDDS::Protocols::Serial::ISerialChannel
{
public:
    std::string name() const override { return "flaky-gnss"; }
    void open() override { _open = true; ++openCount; }
    void close() noexcept override { _open = false; }
    bool isOpen() const noexcept override { return _open; }
    std::size_t write(const std::uint8_t*, std::size_t size) override { return size; }
    std::vector<std::uint8_t> read(std::size_t size, Poco::Timespan) override
    {
        if (_fail.exchange(false)) throw std::runtime_error("GNSS link lost");
        std::vector<std::uint8_t> result;
        {
            std::lock_guard<std::mutex> lock(_mutex);
            while (!_bytes.empty() && result.size() < size)
            {
                result.push_back(_bytes.front());
                _bytes.pop_front();
            }
        }
        if (result.empty()) Poco::Thread::sleep(5);
        return result;
    }
    void inject(const std::string& text)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _bytes.insert(_bytes.end(), text.begin(), text.end());
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
}

int main()
{
    auto channel = std::make_shared<FlakySerialChannel>();
    PocoDDS::Devices::GnssRecoveryPolicy policy;
    policy.reconnectDelay = std::chrono::milliseconds(10);
    policy.readTimeout = std::chrono::milliseconds(10);
    // Keep enough margin for heavily loaded CI workers; the final assertion still
    // proves the stale transition without racing the earlier recovery checks.
    policy.staleAfter = std::chrono::milliseconds(500);
    PocoDDS::Devices::NmeaGnssDevice device("gnss-recovery", channel, policy);
    device.setPositionHandler([](const auto&) { throw std::runtime_error("consumer failure"); });
    device.start();
    if (device.snapshot().state != PocoDDS::Devices::DeviceState::offline) return 1;

    channel->inject(
        "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n");
    if (!waitFor([&] { return device.hasFix(); }, 500)) return 2;
    if (device.snapshot().state != PocoDDS::Devices::DeviceState::ready) return 3;

    channel->inject(
        "$GPRMC,123519,V,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*7D\r\n");
    if (!waitFor([&] {
            return !device.hasFix() &&
                device.snapshot().state == PocoDDS::Devices::DeviceState::offline;
        }, 500)) return 4;
    const auto invalid = device.diagnostics();
    const auto invalidFailure = device.failure();
    if (invalid.lastError != "GNSS fix invalid" ||
        invalidFailure.code != "PDR-DEVICE-GNSS-FIX_INVALID" ||
        !invalidFailure.active || !invalidFailure.retryable) return 5;

    channel->inject(
        "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n");
    if (!waitFor([&] { return device.hasFix(); }, 500)) return 6;

    channel->inject(
        "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*00\r\n");
    if (!waitFor([&] { return device.diagnostics().failedOperations >= 2; }, 500)) return 7;
    if (!device.hasFix()) return 8;

    channel->failNext();
    if (!waitFor([&] {
            return device.diagnostics().reconnectAttempts >= 1 && channel->openCount >= 2;
        }, 500)) return 9;
    if (device.snapshot().state != PocoDDS::Devices::DeviceState::offline) return 10;

    channel->inject(
        "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n");
    if (!waitFor([&] { return device.hasFix(); }, 500)) return 11;
    if (!waitFor([&] {
            return device.snapshot().state == PocoDDS::Devices::DeviceState::offline;
        }, 1500)) return 12;
    const auto stale = device.diagnostics();
    const auto staleFailure = device.failure();
    if (stale.lastError != "GNSS fix stale" ||
        staleFailure.code != "PDR-DEVICE-GNSS-FIX_STALE" ||
        !staleFailure.active) return 13;
    device.stop();
    return 0;
}
