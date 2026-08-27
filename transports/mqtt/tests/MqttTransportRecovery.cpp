#include "PocoDDS/MqttTransport/MqttTransport.h"

#include "Poco/Net/ServerSocket.h"
#include "Poco/Net/SocketAddress.h"
#include "Poco/Timespan.h"

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <iostream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace
{
void receiveAll(Poco::Net::StreamSocket& socket, void* data, std::size_t size)
{
    auto* bytes = static_cast<std::uint8_t*>(data);
    std::size_t offset = 0;
    while (offset < size)
    {
        const int received = socket.receiveBytes(
            bytes + offset, static_cast<int>(size - offset));
        if (received <= 0)
            throw std::runtime_error("MQTT recovery broker connection closed");
        offset += static_cast<std::size_t>(received);
    }
}

struct Packet
{
    std::uint8_t header{0};
    std::vector<std::uint8_t> body;
};

Packet receivePacket(Poco::Net::StreamSocket& socket)
{
    Packet packet;
    receiveAll(socket, &packet.header, 1);
    std::size_t remaining = 0;
    std::size_t multiplier = 1;
    for (int index = 0; index < 4; ++index)
    {
        std::uint8_t encoded = 0;
        receiveAll(socket, &encoded, 1);
        remaining += (encoded & 0x7fU) * multiplier;
        if ((encoded & 0x80U) == 0)
            break;
        multiplier *= 128;
    }
    packet.body.resize(remaining);
    if (remaining != 0)
        receiveAll(socket, packet.body.data(), remaining);
    return packet;
}

void sendPacket(Poco::Net::StreamSocket& socket, std::uint8_t header,
                const std::vector<std::uint8_t>& body)
{
    std::vector<std::uint8_t> wire{header};
    std::size_t remaining = body.size();
    do
    {
        auto encoded = static_cast<std::uint8_t>(remaining % 128);
        remaining /= 128;
        if (remaining != 0)
            encoded |= 0x80U;
        wire.push_back(encoded);
    } while (remaining != 0);
    wire.insert(wire.end(), body.begin(), body.end());
    socket.sendBytes(wire.data(), static_cast<int>(wire.size()));
}

std::vector<std::uint8_t> packetIdentifier(const Packet& packet)
{
    if ((packet.header >> 4) != 8 || packet.body.size() < 2)
        throw std::runtime_error("expected MQTT SUBSCRIBE");
    return {packet.body[0], packet.body[1]};
}

std::string subscriptionTopic(const Packet& packet)
{
    if ((packet.header >> 4) != 8 || packet.body.size() < 5)
        throw std::runtime_error("invalid MQTT SUBSCRIBE frame");
    const auto topicSize =
        (static_cast<std::size_t>(packet.body[2]) << 8) | packet.body[3];
    if (topicSize == 0 || 4 + topicSize >= packet.body.size())
        throw std::runtime_error("invalid MQTT SUBSCRIBE topic");
    return {reinterpret_cast<const char*>(packet.body.data() + 4), topicSize};
}

void sendPublish(Poco::Net::StreamSocket& socket, const std::string& topic,
                 const std::vector<std::uint8_t>& payload)
{
    std::vector<std::uint8_t> body{
        static_cast<std::uint8_t>((topic.size() >> 8) & 0xffU),
        static_cast<std::uint8_t>(topic.size() & 0xffU)};
    body.insert(body.end(), topic.begin(), topic.end());
    body.insert(body.end(), payload.begin(), payload.end());
    sendPacket(socket, 0x30, body);
}

bool waitUntil(const std::function<bool()>& predicate,
               std::chrono::steady_clock::duration timeout)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (!predicate() && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    return predicate();
}
} // namespace

int main()
{
    using namespace PocoDDS::MqttTransport;
    using namespace PocoDDS::RuntimeCore;

    const TopicSpec topic{"mqtt.recovery", "example.Recovery", "1",
                          Delivery::reliable, false};
    const auto frame = [&topic](const std::string& id, std::uint8_t value)
    {
        Message message;
        message.type = topic.messageType;
        message.schemaVersion = topic.schemaVersion;
        message.context.messageId = id;
        message.payload = std::make_shared<const Payload>(Payload{value});
        const auto encoded = encodeMessageFrame(topic, message);
        if (!encoded)
            throw std::runtime_error("cannot encode MQTT recovery frame");
        return encoded.value();
    };
    const auto beforeDrop = frame("before-drop", 0x10);
    const auto afterDrop = frame("after-drop", 0x20);

    Poco::Net::ServerSocket server(Poco::Net::SocketAddress("127.0.0.1", 0));
    std::string brokerError;
    int subscribeCount = 0;
    std::thread broker([&]
    {
        try
        {
            for (int session = 0; session < 2; ++session)
            {
                auto socket = server.acceptConnection();
                socket.setReceiveTimeout(Poco::Timespan(5, 0));
                if ((receivePacket(socket).header >> 4) != 1)
                    throw std::runtime_error("expected MQTT CONNECT");
                sendPacket(socket, 0x20, {0x00, 0x00});
                const auto subscribe = receivePacket(socket);
                if (subscriptionTopic(subscribe) != "pdr/mqtt.recovery")
                    throw std::runtime_error("unexpected MQTT recovery topic");
                ++subscribeCount;
                auto response = packetIdentifier(subscribe);
                response.push_back(0x01);
                sendPacket(socket, 0x90, response);
                sendPublish(socket, "pdr/mqtt.recovery",
                            session == 0 ? beforeDrop : afterDrop);
                if (session == 0)
                {
                    std::this_thread::sleep_for(std::chrono::milliseconds(50));
                    socket.shutdown();
                    socket.close();
                }
                else if ((receivePacket(socket).header >> 4) != 14)
                    throw std::runtime_error("expected MQTT DISCONNECT after recovery");
            }
        }
        catch (const std::exception& exception)
        {
            brokerError = exception.what();
        }
    });

    MqttTransportOptions options;
    options.serverUri =
        "tcp://127.0.0.1:" + std::to_string(server.address().port());
    options.clientId = "pdr-mqtt-transport-recovery";
    MqttTransport transport(std::move(options));
    std::mutex mutex;
    std::condition_variable changed;
    std::vector<std::string> received;
    auto subscription = transport.subscribe(
        topic, [&](const TopicSpec&, const Message& message)
        {
            {
                std::lock_guard<std::mutex> lock(mutex);
                received.push_back(message.context.messageId);
            }
            changed.notify_all();
            // Keep the callback active after delivery becomes observable. This
            // deterministically exercises stop() while Paho is between callback
            // dispatch and its internal queue cleanup.
            std::this_thread::sleep_for(std::chrono::milliseconds(25));
        });

    const auto started = transport.start();
    if (!started)
    {
        server.close();
        broker.join();
        std::cerr << "MQTT_TRANSPORT_RECOVERY_FAIL initial="
                  << started.error().message << '\n';
        return 1;
    }
    {
        std::unique_lock<std::mutex> lock(mutex);
        changed.wait_for(lock, std::chrono::seconds(3), [&] { return received.size() >= 1; });
    }
    const bool firstDelivered = [&]
    {
        std::lock_guard<std::mutex> lock(mutex);
        return received.size() >= 1 && received.front() == "before-drop";
    }();
    const bool lossObserved = waitUntil(
        [&] { return !transport.running(); }, std::chrono::seconds(3));
    if (!lossObserved)
        transport.stop();
    const auto restarted = transport.start();
    bool secondDelivered = false;
    if (restarted)
    {
        std::unique_lock<std::mutex> lock(mutex);
        changed.wait_for(lock, std::chrono::seconds(3), [&] { return received.size() >= 2; });
        secondDelivered = received.size() == 2 && received.back() == "after-drop";
        lock.unlock();
        transport.stop();
    }
    else
    {
        server.close();
    }
    broker.join();
    subscription.reset();

    if (!firstDelivered || !lossObserved || !restarted || !secondDelivered ||
        subscribeCount != 2 || !brokerError.empty())
    {
        std::cerr << "MQTT_TRANSPORT_RECOVERY_FAIL first=" << firstDelivered
                  << " loss=" << lossObserved << " restart=" << bool(restarted)
                  << " second=" << secondDelivered << " subscriptions=" << subscribeCount
                  << " broker=" << brokerError << '\n';
        return 2;
    }
    std::cout << "PDR_MQTT_TRANSPORT_RECOVERY_PASS unexpectedDrop=1 reconnect=1 "
                 "subscriptionRestored=1 delivery=2 callbackTeardown=1\n";
    return 0;
}
