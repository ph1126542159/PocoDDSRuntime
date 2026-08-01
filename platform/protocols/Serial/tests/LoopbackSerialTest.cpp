#include "PocoDDS/Protocols/Serial/LoopbackSerialChannel.h"

#include "Poco/Thread.h"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <thread>
#include <vector>

int main()
{
    PocoDDS::Protocols::Serial::LoopbackSerialChannel channel("test");
    channel.open();
    const std::vector<std::uint8_t> expected{1, 2, 3, 4};
    if (channel.write(expected.data(), expected.size()) != expected.size() ||
        channel.read(16, Poco::Timespan(0, 100000)) != expected)
        return 1;

    std::atomic_bool woke{false};
    std::thread reader([&] {
        try
        {
            static_cast<void>(channel.read(16, Poco::Timespan(5, 0)));
        }
        catch (...)
        {
            woke = true;
        }
    });
    Poco::Thread::sleep(10);
    const auto started = std::chrono::steady_clock::now();
    channel.close();
    reader.join();
    const auto elapsed = std::chrono::steady_clock::now() - started;
    if (!woke || elapsed > std::chrono::seconds(1) || channel.isOpen())
        return 2;
    std::cout << "SERIAL_LOOPBACK_PASS echo=4 close-wakeup=1\n";
    return 0;
}
