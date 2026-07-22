#include "PocoDDS/Control/ContractCodec.h"
#include "PocoDDS/Control/DiscoveryAgent.h"
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
constexpr const char* ReadyTopic = "pdr.acceptance.fastdds.ready";
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
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Control::DiscoveryAgent discovery(transport, registry, "acceptance-subscriber",
                                               std::chrono::milliseconds(100),
                                               std::chrono::seconds(3));
    auto discoveryDiagnostic = transport.subscribe(
        PocoDDS::Control::ComponentTopic,
        [](const auto& message)
        {
            try
            {
                const auto manifest = PocoDDS::Control::decodeComponentManifest(message.payload);
                std::cout << "FAST_DDS_MANIFEST_DECODE_PASS " << manifest.component.id << '\n'
                          << std::flush;
            }
            catch (const std::exception& error)
            {
                std::cout << "FAST_DDS_MANIFEST_DECODE_FAIL " << error.what() << '\n' << std::flush;
            }
        });
    std::mutex mutex;
    std::condition_variable changed;
    bool passed = false;
    auto subscription = transport.subscribe(
        Topic,
        [&](const auto& message)
        {
            const std::string payload(reinterpret_cast<const char*>(message.payload.data()),
                                      message.payload.size());
            const auto valid = message.type == "PocoDDS.Acceptance.v1" &&
                               message.traceParent == TraceParent &&
                               payload == "FAST_DDS_TWO_PROCESS_PAYLOAD";
            {
                std::lock_guard lock(mutex);
                passed = valid;
            }
            if (valid)
                std::cout << "FAST_DDS_RAW_RECEIVE_PASS\n" << std::flush;
            changed.notify_all();
        });
    const auto messageDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(20);
    std::unique_lock lock(mutex);
    while (!passed && std::chrono::steady_clock::now() < messageDeadline)
    {
        lock.unlock();
        transport.publish({ReadyTopic, "PocoDDS.AcceptanceReady.v1", {}, {}});
        lock.lock();
        changed.wait_for(lock, std::chrono::milliseconds(100), [&]() { return passed; });
    }
    if (!passed)
        return 2;
    lock.unlock();
    const auto discoveryDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (!registry.find("acceptance.publisher").has_value() &&
           std::chrono::steady_clock::now() < discoveryDeadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    if (!registry.find("acceptance.publisher").has_value())
    {
        std::cout << "FAST_DDS_DISCOVERY_MISSING\n" << std::flush;
        return 5;
    }
    std::cout << "FAST_DDS_DISCOVERY_PASS\n" << std::flush;
    std::ofstream marker(markerPath, std::ios::trunc);
    marker << "FAST_DDS_TWO_PROCESS_PASS\n";
    std::cout << "FAST_DDS_TWO_PROCESS_PASS\n";
    return marker ? 0 : 3;
}

int publish(std::uint32_t domainId, PocoDDS::Transport::FastDDSTransportMode mode)
{
    PocoDDS::Transport::FastDDSTransport transport({domainId, "pdr-dds-publisher", mode});
    std::mutex readyMutex;
    std::condition_variable readyChanged;
    bool subscriberReady = false;
    auto readySubscription =
        transport.subscribe(ReadyTopic,
                            [&](const auto& message)
                            {
                                if (message.type != "PocoDDS.AcceptanceReady.v1")
                                    return;
                                {
                                    std::lock_guard lock(readyMutex);
                                    subscriberReady = true;
                                }
                                readyChanged.notify_all();
                            });
    std::unique_lock readyLock(readyMutex);
    if (!readyChanged.wait_for(readyLock, std::chrono::seconds(15),
                               [&]() { return subscriberReady; }))
        return 4;
    readyLock.unlock();
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Control::DiscoveryAgent discovery(transport, registry, "acceptance-publisher",
                                               std::chrono::milliseconds(100),
                                               std::chrono::seconds(3));
    discovery.registerLocal(
        {"acceptance.publisher",
         "Acceptance Publisher",
         "localhost",
         0,
         PocoDDS::Core::ComponentKind::Process,
         PocoDDS::Core::ComponentState::Running,
         {{"transport", mode == PocoDDS::Transport::FastDDSTransportMode::SharedMemoryOnly
                            ? "shm"
                            : "network"}}});
    discovery.publishNow();
    const std::string text = "FAST_DDS_TWO_PROCESS_PAYLOAD";
    std::vector<std::byte> payload;
    payload.reserve(text.size());
    for (const auto value : text)
        payload.push_back(std::byte(static_cast<unsigned char>(value)));
    transport.publish({Topic, "PocoDDS.Acceptance.v1", std::move(payload), TraceParent});
    if (!transport.waitForAcknowledgments(std::chrono::seconds(5)))
        return 6;
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
