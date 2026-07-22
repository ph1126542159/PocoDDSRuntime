#include "PocoDDS/Transport/FastDDSTransport.h"

#include <chrono>
#include <condition_variable>
#include <fstream>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>

namespace
{
constexpr const char* Topic = "pdr.acceptance.fastdds";
constexpr const char* TraceParent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";

PocoDDS::Transport::FastDDSTransportMode parseTransportMode(const std::string& value)
{
    if (value == "shm")
        return PocoDDS::Transport::FastDDSTransportMode::SharedMemoryOnly;
    if (value == "network")
        return PocoDDS::Transport::FastDDSTransportMode::NetworkOnly;
    throw std::invalid_argument("transport mode must be shm or network");
}

int subscribe(const std::string& markerPath, std::uint32_t domainId,
              PocoDDS::Transport::FastDDSTransportMode mode)
{
    PocoDDS::Transport::FastDDSTransport transport({domainId, "pdr-dds-subscriber", mode});
    std::mutex mutex;
    std::condition_variable changed;
    bool passed = false;
    auto subscription = transport.subscribe(
        Topic,
        [&](const auto& message)
        {
            const std::string payload(reinterpret_cast<const char*>(message.payload.data()),
                                      message.payload.size());
            {
                std::lock_guard lock(mutex);
                passed = message.type == "PocoDDS.Acceptance.v1" &&
                         message.traceParent == TraceParent &&
                         payload == "FAST_DDS_TWO_PROCESS_PAYLOAD";
            }
            changed.notify_all();
        });
    std::unique_lock lock(mutex);
    if (!changed.wait_for(lock, std::chrono::seconds(20), [&]() { return passed; }))
        return 2;
    std::ofstream marker(markerPath, std::ios::trunc);
    marker << "FAST_DDS_TWO_PROCESS_PASS\n";
    std::cout << "FAST_DDS_TWO_PROCESS_PASS\n";
    return marker ? 0 : 3;
}

int publish(std::uint32_t domainId, PocoDDS::Transport::FastDDSTransportMode mode)
{
    PocoDDS::Transport::FastDDSTransport transport({domainId, "pdr-dds-publisher", mode});
    if (!transport.waitForPeer(std::chrono::seconds(15)))
        return 4;
    const std::string text = "FAST_DDS_TWO_PROCESS_PAYLOAD";
    std::vector<std::byte> payload;
    payload.reserve(text.size());
    for (const auto value : text)
        payload.push_back(std::byte(static_cast<unsigned char>(value)));
    transport.publish({Topic, "PocoDDS.Acceptance.v1", std::move(payload), TraceParent});
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    std::cout << "FAST_DDS_PUBLISH_PASS\n";
    return 0;
}
} // namespace

int main(int argc, char* argv[])
{
    if (argc < 4)
    {
        std::cerr << "usage: pdr-dds-probe <publish|subscribe> <domain-id> "
                     "<shm|network> [marker-path]\n";
        return 1;
    }
    const auto domainId = static_cast<std::uint32_t>(std::stoul(argv[2]));
    const auto transportMode = parseTransportMode(argv[3]);
    const std::string mode = argv[1];
    if (mode == "publish")
        return publish(domainId, transportMode);
    if (mode == "subscribe" && argc == 5)
        return subscribe(argv[4], domainId, transportMode);
    return 1;
}
