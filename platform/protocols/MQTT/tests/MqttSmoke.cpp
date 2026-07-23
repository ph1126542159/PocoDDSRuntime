#include "PocoDDS/Protocols/MQTT/MqttClient.h"

#include "Poco/Net/ServerSocket.h"
#include "Poco/Net/SocketAddress.h"

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <iostream>
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
        const int received =
            socket.receiveBytes(bytes + offset, static_cast<int>(size - offset));
        if (received <= 0)
            throw std::runtime_error("MQTT smoke broker connection closed");
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
    for (int i = 0; i < 4; ++i)
    {
        std::uint8_t encoded = 0;
        receiveAll(socket, &encoded, 1);
        remaining += (encoded & 0x7F) * multiplier;
        if ((encoded & 0x80) == 0)
            break;
        multiplier *= 128;
    }
    packet.body.resize(remaining);
    if (remaining)
        receiveAll(socket, packet.body.data(), remaining);
    return packet;
}

void sendPacket(Poco::Net::StreamSocket& socket,
                std::uint8_t header,
                const std::vector<std::uint8_t>& body)
{
    std::vector<std::uint8_t> wire{header};
    std::size_t remaining = body.size();
    do
    {
        std::uint8_t encoded = static_cast<std::uint8_t>(remaining % 128);
        remaining /= 128;
        if (remaining)
            encoded |= 0x80;
        wire.push_back(encoded);
    } while (remaining);
    wire.insert(wire.end(), body.begin(), body.end());
    socket.sendBytes(wire.data(), static_cast<int>(wire.size()));
}
} // namespace

int main()
{
    Poco::Net::ServerSocket server(Poco::Net::SocketAddress("127.0.0.1", 0));
    std::string brokerError;
    std::thread broker([&] {
        try
        {
            auto socket = server.acceptConnection();
            const auto connect = receivePacket(socket);
            if ((connect.header >> 4) != 1)
                throw std::runtime_error("expected MQTT CONNECT");
            sendPacket(socket, 0x20, {0x00, 0x00});

            const auto subscribe = receivePacket(socket);
            if ((subscribe.header >> 4) != 8 || subscribe.body.size() < 2)
                throw std::runtime_error("expected MQTT SUBSCRIBE");
            sendPacket(socket, 0x90,
                       {subscribe.body[0], subscribe.body[1], 0x01});

            const std::string topic = "pdr/test";
            const std::string payload = "from-broker";
            std::vector<std::uint8_t> publishBody{
                static_cast<std::uint8_t>(topic.size() >> 8),
                static_cast<std::uint8_t>(topic.size())};
            publishBody.insert(publishBody.end(), topic.begin(), topic.end());
            publishBody.insert(publishBody.end(), payload.begin(), payload.end());
            sendPacket(socket, 0x30, publishBody);

            const auto publish = receivePacket(socket);
            if ((publish.header >> 4) != 3 || (publish.header & 0x06) != 0x02 ||
                publish.body.size() < 4)
                throw std::runtime_error("expected MQTT QoS 1 PUBLISH");
            const std::size_t topicLength =
                (static_cast<std::size_t>(publish.body[0]) << 8) | publish.body[1];
            const std::size_t packetIdOffset = 2 + topicLength;
            if (packetIdOffset + 2 > publish.body.size())
                throw std::runtime_error("invalid MQTT PUBLISH");
            sendPacket(socket, 0x40,
                       {publish.body[packetIdOffset], publish.body[packetIdOffset + 1]});
            const auto disconnect = receivePacket(socket);
            if ((disconnect.header >> 4) != 14)
                throw std::runtime_error("expected MQTT DISCONNECT");
        }
        catch (const std::exception& exception)
        {
            brokerError = exception.what();
        }
    });

    std::mutex mutex;
    std::condition_variable changed;
    std::string receivedPayload;
    PocoDDS::Protocols::MQTT::MqttClient::Options options;
    options.serverUri = "tcp://127.0.0.1:" + std::to_string(server.address().port());
    options.clientId = "pdr-mqtt-smoke";
    PocoDDS::Protocols::MQTT::MqttClient client(std::move(options));
    client.setMessageHandler([&](const PocoDDS::Protocols::MQTT::Message& message) {
        if (message.topic == "pdr/test")
        {
            std::lock_guard<std::mutex> lock(mutex);
            receivedPayload = message.payload;
            changed.notify_all();
        }
    });
    client.open();
    client.subscribe("pdr/test");
    {
        std::unique_lock<std::mutex> lock(mutex);
        changed.wait_for(lock, std::chrono::seconds(3),
                         [&] { return !receivedPayload.empty(); });
    }
    client.publish("pdr/test", "from-client");
    client.close();
    broker.join();

    if (!brokerError.empty() || receivedPayload != "from-broker")
    {
        std::cerr << "MQTT_SMOKE_FAIL broker=" << brokerError
                  << " payload=" << receivedPayload << '\n';
        return 2;
    }
    std::cout << "MQTT_SMOKE_PASS subscribe=1 publish=1 payload=" << receivedPayload << '\n';
    return 0;
}
