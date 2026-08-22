#include "PocoDDS/MqttTransport/MqttTransport.h"
#include "PocoDDS/MqttTransport/Registration.h"
#include "PocoDDS/RuntimeCore/Testing/TransportConformance.h"

#include "Poco/Net/ServerSocket.h"
#include "Poco/Net/SocketAddress.h"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <future>
#include <iostream>
#include <memory>
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
        const int received = socket.receiveBytes(bytes + offset, static_cast<int>(size - offset));
        if (received <= 0)
            throw std::runtime_error("MQTT transport broker connection closed");
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
    const auto type = packet.header >> 4;
    std::size_t offset = 0;
    if (type == 3)
    {
        if (packet.body.size() < 4)
            throw std::runtime_error("MQTT PUBLISH frame is too small");
        const auto topicSize = (static_cast<std::size_t>(packet.body[0]) << 8) | packet.body[1];
        offset = 2 + topicSize;
    }
    if (offset + 2 > packet.body.size())
        throw std::runtime_error("MQTT packet identifier is missing");
    return {packet.body[offset], packet.body[offset + 1]};
}

std::string subscriptionTopic(const Packet& packet)
{
    if ((packet.header >> 4) != 8 || packet.body.size() < 5)
        throw std::runtime_error("invalid MQTT SUBSCRIBE frame");
    const auto topicSize = (static_cast<std::size_t>(packet.body[2]) << 8) | packet.body[3];
    if (topicSize == 0 || 4 + topicSize >= packet.body.size())
        throw std::runtime_error("invalid MQTT SUBSCRIBE topic");
    return {reinterpret_cast<const char*>(packet.body.data() + 4), topicSize};
}

void sendPublish(Poco::Net::StreamSocket& socket, const std::string& topic,
                 const std::vector<std::uint8_t>& payload)
{
    if (topic.size() > 0xffffU)
        throw std::runtime_error("MQTT test topic is too long");
    std::vector<std::uint8_t> body{static_cast<std::uint8_t>((topic.size() >> 8) & 0xffU),
                                   static_cast<std::uint8_t>(topic.size() & 0xffU)};
    body.insert(body.end(), topic.begin(), topic.end());
    body.insert(body.end(), payload.begin(), payload.end());
    sendPacket(socket, 0x30, body);
}
} // namespace

int main()
{
    using namespace PocoDDS::MqttTransport;
    using namespace PocoDDS::RuntimeCore;
    using namespace PocoDDS::RuntimeCore::Testing;

    TopicSpec remoteTopic{"mqtt.remote", "example.Remote", "1", Delivery::reliable, false};
    Message remoteMessage;
    remoteMessage.type = remoteTopic.messageType;
    remoteMessage.schemaVersion = remoteTopic.schemaVersion;
    remoteMessage.payload = std::make_shared<const Payload>(Payload{0x10, 0x20, 0x30});
    remoteMessage.context.messageId = "from-broker";
    const auto remoteFrame = encodeMessageFrame(remoteTopic, remoteMessage);
    if (!remoteFrame)
        return 1;

    Poco::Net::ServerSocket server(Poco::Net::SocketAddress("127.0.0.1", 0));
    std::string brokerError;
    std::atomic<int> remoteSubscribeCount{0};
    std::thread broker(
        [&]
        {
            try
            {
                for (int session = 0; session < 2; ++session)
                {
                    auto socket = server.acceptConnection();
                    if ((receivePacket(socket).header >> 4) != 1)
                        throw std::runtime_error("expected MQTT CONNECT");
                    sendPacket(socket, 0x20, {0x00, 0x00});
                    bool disconnected = false;
                    while (!disconnected)
                    {
                        const auto packet = receivePacket(socket);
                        switch (packet.header >> 4)
                        {
                        case 3:
                            sendPacket(socket, 0x40, packetIdentifier(packet));
                            break;
                        case 8:
                        {
                            const auto topic = subscriptionTopic(packet);
                            auto response = packetIdentifier(packet);
                            response.push_back(0x01);
                            sendPacket(socket, 0x90, response);
                            if (topic == "pdr/mqtt.remote")
                            {
                                ++remoteSubscribeCount;
                                sendPublish(socket, topic, remoteFrame.value());
                            }
                            break;
                        }
                        case 10:
                            sendPacket(socket, 0xb0, packetIdentifier(packet));
                            break;
                        case 12:
                            sendPacket(socket, 0xd0, {});
                            break;
                        case 14:
                            disconnected = true;
                            break;
                        default:
                            throw std::runtime_error("unexpected MQTT packet type");
                        }
                    }
                }
            }
            catch (const std::exception& exception)
            {
                brokerError = exception.what();
            }
        });

    MqttTransportOptions options;
    options.serverUri = "tcp://127.0.0.1:" + std::to_string(server.address().port());
    options.clientId = "pdr-mqtt-transport-smoke";
    MqttTransport transport(std::move(options));
    std::promise<std::string> receivedMessageId;
    auto receivedFuture = receivedMessageId.get_future();
    auto remoteSubscription = transport.subscribe(
        remoteTopic, [&receivedMessageId](const TopicSpec&, const Message& message)
        { receivedMessageId.set_value(message.context.messageId); });
    const auto started = transport.start();
    if (!started)
    {
        broker.join();
        return 2;
    }
    if (receivedFuture.wait_for(std::chrono::seconds(3)) != std::future_status::ready ||
        receivedFuture.get() != "from-broker")
    {
        remoteSubscription.reset();
        transport.stop();
        broker.join();
        std::cerr << "MQTT_TRANSPORT_FAIL broker-to-adapter delivery timed out\n";
        return 3;
    }
    // Remove the subscription while offline. It must not be restored by MqttClient::open() on
    // the second session; the conformance run below establishes a different subscription.
    transport.stop();
    remoteSubscription.reset();
    const auto restarted = transport.start();
    if (!restarted)
    {
        broker.join();
        return 4;
    }
    const auto conformance =
        runTransportConformance(transport, {"mqtt", {false, false, true, false, true, false}});
    transport.stop();
    broker.join();
    if (!conformance || conformance.value().passedChecks.size() != 7 || !brokerError.empty() ||
        remoteSubscribeCount.load() != 1)
    {
        std::cerr << "MQTT_TRANSPORT_FAIL broker=" << brokerError
                  << " conformance=" << (conformance ? "pass" : conformance.error().message)
                  << " remoteSubscriptions=" << remoteSubscribeCount.load() << '\n';
        return 5;
    }

    TransportRegistry registry;
    auto registration = registerMqttTransport(registry);
    if (!registration || registry.descriptors().size() != 1 ||
        registry.descriptors().front().id != "mqtt")
        return 6;
    const auto invalidConfiguration = registry.create("mqtt", {{"serverUri", "tcp://127.0.0.1:1"},
                                                               {"clientId", "invalid-config"},
                                                               {"verifyHostname", "sometimes"}});
    if (invalidConfiguration ||
        invalidConfiguration.error().code != RuntimeErrorCode::invalidArgument)
        return 7;
    std::cout << "PDR_MQTT_TRANSPORT_PASS codec=PDRM/1 broker=bidirectional conformance=7 "
                 "registry=verified config=strict\n";
    return 0;
}
