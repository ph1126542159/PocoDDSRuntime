#include "PocoDDS/Protocols/ROS/BridgeClient.h"

#include <Poco/JSON/Parser.h>
#include <Poco/Net/HTTPClientSession.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/StreamCopier.h>
#include <Poco/UUIDGenerator.h>

#include <sstream>
#include <utility>
#include <vector>

namespace PocoDDS::Protocols::ROS
{

namespace
{
std::string stringify(const Poco::JSON::Object::Ptr& object)
{
    std::ostringstream stream;
    object->stringify(stream);
    return stream.str();
}
}

BridgeClient::BridgeClient(Poco::URI uri): _uri(std::move(uri))
{
}

BridgeClient::~BridgeClient()
{
    try
    {
        disconnect();
    }
    catch (...)
    {
    }
}

void BridgeClient::connect()
{
    std::lock_guard lock(_mutex);
    if (_socket)
        return;

    Poco::Net::HTTPClientSession session(_uri.getHost(), _uri.getPort());
    Poco::Net::HTTPRequest request(
        Poco::Net::HTTPRequest::HTTP_GET,
        _uri.getPathEtc().empty() ? "/" : _uri.getPathEtc(),
        Poco::Net::HTTPMessage::HTTP_1_1);
    Poco::Net::HTTPResponse response;
    _socket = std::make_unique<Poco::Net::WebSocket>(session, request, response);
}

void BridgeClient::disconnect()
{
    std::unique_ptr<Poco::Net::WebSocket> socket;
    {
        std::lock_guard lock(_mutex);
        socket = std::move(_socket);
        _subscriptions.clear();
    }
    if (socket)
    {
        socket->shutdown();
        socket->close();
    }
}

bool BridgeClient::isConnected() const
{
    std::lock_guard lock(_mutex);
    return static_cast<bool>(_socket);
}

std::string BridgeClient::subscribe(const std::string& topic)
{
    return subscribe(topic, {});
}

std::string BridgeClient::subscribe(const std::string& topic, const SubscribeOptions& options)
{
    const auto id = Poco::UUIDGenerator::defaultGenerator().createOne().toString();
    const auto request = makeSubscribeRequest(topic, id, options);
    std::lock_guard lock(_mutex);
    if (!_socket)
        throw Poco::IllegalStateException("ROS bridge is not connected");
    sendText(request);
    _subscriptions.emplace(id, topic);
    return id;
}

void BridgeClient::unsubscribe(const std::string& topic, const std::string& id)
{
    const auto request = makeUnsubscribeRequest(topic, id);
    std::lock_guard lock(_mutex);
    if (!_socket)
        throw Poco::IllegalStateException("ROS bridge is not connected");
    sendText(request);
    if (!id.empty())
        _subscriptions.erase(id);
}

void BridgeClient::unsubscribeAll()
{
    std::lock_guard lock(_mutex);
    if (!_socket)
        return;
    for (const auto& [id, topic] : _subscriptions)
        sendText(makeUnsubscribeRequest(topic, id));
    _subscriptions.clear();
}

Poco::JSON::Object::Ptr BridgeClient::receiveMessage(const Poco::Timespan& timeout)
{
    MessageHandler handler;
    Poco::JSON::Object::Ptr object;
    {
        std::lock_guard lock(_mutex);
        if (!_socket)
            throw Poco::IllegalStateException("ROS bridge is not connected");
        if (!_socket->poll(timeout, Poco::Net::Socket::SELECT_READ))
            return {};

        std::vector<char> buffer(64 * 1024);
        int flags = 0;
        const int count = _socket->receiveFrame(buffer.data(), static_cast<int>(buffer.size()), flags);
        if (count <= 0)
            return {};
        Poco::JSON::Parser parser;
        object = parser.parse(std::string(buffer.data(), static_cast<std::size_t>(count)))
                     .extract<Poco::JSON::Object::Ptr>();
        handler = _handler;
    }
    if (handler)
        handler(object);
    return object;
}

void BridgeClient::setMessageHandler(MessageHandler handler)
{
    std::lock_guard lock(_mutex);
    _handler = std::move(handler);
}

std::string BridgeClient::makeSubscribeRequest(
    const std::string& topic,
    const std::string& id,
    const SubscribeOptions& options)
{
    auto object = Poco::JSON::Object::Ptr(new Poco::JSON::Object);
    object->set("op", "subscribe");
    object->set("topic", topic);
    object->set("id", id);
    if (!options.type.empty()) object->set("type", options.type);
    if (options.throttleRate != 0) object->set("throttle_rate", options.throttleRate);
    if (options.queueLength != 0) object->set("queue_length", options.queueLength);
    if (options.fragmentSize != 0) object->set("fragment_size", options.fragmentSize);
    if (!options.compression.empty()) object->set("compression", options.compression);
    return stringify(object);
}

std::string BridgeClient::makeUnsubscribeRequest(const std::string& topic, const std::string& id)
{
    auto object = Poco::JSON::Object::Ptr(new Poco::JSON::Object);
    object->set("op", "unsubscribe");
    object->set("topic", topic);
    if (!id.empty()) object->set("id", id);
    return stringify(object);
}

void BridgeClient::sendText(const std::string& payload)
{
    _socket->sendFrame(
        payload.data(),
        static_cast<int>(payload.size()),
        Poco::Net::WebSocket::FRAME_TEXT);
}

} // namespace PocoDDS::Protocols::ROS
