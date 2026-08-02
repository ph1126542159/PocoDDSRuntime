#include "PocoDDS/Protocols/ROS/BridgeClient.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <Poco/JSON/Parser.h>
#include <Poco/Buffer.h>
#include <Poco/Net/HTTPClientSession.h>
#include <Poco/Net/HTTPSClientSession.h>
#include <Poco/Net/Context.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/StreamCopier.h>
#include <Poco/UUIDGenerator.h>

#include <sstream>
#include <chrono>
#include <stdexcept>
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

BridgeClient::BridgeClient(Options options)
    : _uri(std::move(options.uri)),
      _maximumMessageSize(options.maximumMessageSize),
      _connectTimeoutSeconds(options.connectTimeoutSeconds),
      _authorization(std::move(options.authorization)),
      _trustStore(std::move(options.trustStore)),
      _clientCertificate(std::move(options.clientCertificate)),
      _privateKey(std::move(options.privateKey)),
      _verifyServerCertificate(options.verifyServerCertificate),
      _verifyHostname(options.verifyHostname)
{
    if (_uri.getHost().empty())
        throw std::invalid_argument("ROS bridge URI host is required");
    if (_maximumMessageSize == 0)
        throw std::invalid_argument("ROS bridge maximum message size must be positive");
    if (_connectTimeoutSeconds <= 0)
        throw std::invalid_argument("ROS bridge connect timeout must be positive");
    if (_uri.getScheme() != "ws" && _uri.getScheme() != "wss")
        throw std::invalid_argument("ROS bridge URI scheme must be ws or wss");
    const bool tls = _uri.getScheme() == "wss";
    if ((!_trustStore.empty() || !_clientCertificate.empty() || !_privateKey.empty()) && !tls)
        throw std::invalid_argument("ROS bridge TLS material requires a wss URI");
    if (_clientCertificate.empty() != _privateKey.empty())
        throw std::invalid_argument(
            "ROS bridge client certificate and private key must be configured together");
}

BridgeClient::BridgeClient(Poco::URI uri, std::size_t maximumMessageSize)
    : BridgeClient(Options{std::move(uri), maximumMessageSize})
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

std::string BridgeClient::name() const
{
    return "rosbridge";
}

void BridgeClient::open()
{
    connect();
}

void BridgeClient::close() noexcept
{
    try { disconnect(); } catch (...) {}
}

bool BridgeClient::isOpen() const noexcept
{
    try { return isConnected(); } catch (...) { return false; }
}

void BridgeClient::connect()
{
    std::lock_guard lock(_mutex);
    if (_socket)
        return;
    PocoDDS::Protocols::ProtocolMetricTimer metric("rosbridge", "connect");

    try
    {
        std::unique_ptr<Poco::Net::HTTPClientSession> session;
        if (_uri.getScheme() == "wss")
        {
            Poco::Net::Context::Params params;
            params.caLocation = _trustStore;
            params.certificateFile = _clientCertificate;
            params.privateKeyFile = _privateKey;
            params.verificationMode = _verifyServerCertificate
                ? Poco::Net::Context::VERIFY_STRICT : Poco::Net::Context::VERIFY_NONE;
            params.loadDefaultCAs = _trustStore.empty();
            Poco::Net::Context::Ptr context =
                new Poco::Net::Context(Poco::Net::Context::TLS_CLIENT_USE, params);
            context->enableExtendedCertificateVerification(
                _verifyServerCertificate && _verifyHostname);
            session = std::make_unique<Poco::Net::HTTPSClientSession>(
                _uri.getHost(), _uri.getPort(), context);
        }
        else
            session = std::make_unique<Poco::Net::HTTPClientSession>(
                _uri.getHost(), _uri.getPort());
        session->setTimeout(Poco::Timespan(_connectTimeoutSeconds, 0));
        Poco::Net::HTTPRequest request(
            Poco::Net::HTTPRequest::HTTP_GET,
            _uri.getPathEtc().empty() ? "/" : _uri.getPathEtc(),
            Poco::Net::HTTPMessage::HTTP_1_1);
        if (!_authorization.empty()) request.set("Authorization", _authorization);
        Poco::Net::HTTPResponse response;
        _socket = std::make_unique<Poco::Net::WebSocket>(*session, request, response);
        _receiveBuffer.clear();
        _receivingTextFragments = false;
        ++_diagnostics.successfulOperations;
        resolveFailure(_diagnostics, _failure);
        metric.success();
    }
    catch (const std::exception& error)
    {
        ++_diagnostics.failedOperations;
        recordFailure(_diagnostics, _failure, "PDR-PROTOCOL-ROS-CONNECT_FAILED",
                      Reliability::FailureKind::transient, true, error.what());
        throw;
    }
}

void BridgeClient::disconnect()
{
    std::unique_ptr<Poco::Net::WebSocket> socket;
    {
        std::lock_guard lock(_mutex);
        socket = std::move(_socket);
        _subscriptions.clear();
        _receiveBuffer.clear();
        _receivingTextFragments = false;
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
    if (topic.empty()) throw std::invalid_argument("ROS subscription topic must not be empty");
    if (options.throttleRate < 0 || options.queueLength < 0 || options.fragmentSize < 0)
        throw std::invalid_argument("ROS subscription numeric options must be non-negative");
    PocoDDS::Protocols::ProtocolMetricTimer metric("rosbridge", "subscribe");
    const auto id = Poco::UUIDGenerator::defaultGenerator().createOne().toString();
    const auto request = makeSubscribeRequest(topic, id, options);
    std::lock_guard lock(_mutex);
    if (!_socket)
        throw Poco::IllegalStateException("ROS bridge is not connected");
    sendText(request);
    _subscriptions.emplace(id, topic);
    metric.success();
    return id;
}

void BridgeClient::unsubscribe(const std::string& topic, const std::string& id)
{
    if (topic.empty()) throw std::invalid_argument("ROS unsubscribe topic must not be empty");
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
    if (timeout.totalMicroseconds() < 0)
        throw std::invalid_argument("ROS receive timeout must be non-negative");
    PocoDDS::Protocols::ProtocolMetricTimer metric("rosbridge", "receive");
    MessageHandler handler;
    std::string text;
    bool messageComplete = false;
    try
    {
        {
            std::lock_guard lock(_mutex);
            if (!_socket)
                throw Poco::IllegalStateException("ROS bridge is not connected");
            const auto deadline = std::chrono::steady_clock::now() +
                std::chrono::microseconds(timeout.totalMicroseconds());
            while (!messageComplete)
            {
            const auto now = std::chrono::steady_clock::now();
            if (now >= deadline)
            {
                ++_diagnostics.timeouts;
                metric.timeout();
                return {};
            }
            const auto remaining = std::chrono::duration_cast<std::chrono::microseconds>(
                deadline - now).count();
            if (!_socket->poll(Poco::Timespan(remaining), Poco::Net::Socket::SELECT_READ))
            {
                ++_diagnostics.timeouts;
                metric.timeout();
                return {};
            }

            Poco::Buffer<char> frame(0);
            int flags = 0;
            const int count = _socket->receiveFrame(frame, flags);
            const int opcode = flags & Poco::Net::WebSocket::FRAME_OP_BITMASK;
            if (opcode == Poco::Net::WebSocket::FRAME_OP_CLOSE)
            {
                _socket->close();
                _socket.reset();
                _receiveBuffer.clear();
                _receivingTextFragments = false;
                ++_diagnostics.failedOperations;
                recordFailure(_diagnostics, _failure, "PDR-PROTOCOL-ROS-PEER_CLOSED",
                              Reliability::FailureKind::transient, true,
                              "ROS bridge closed the WebSocket");
                metric.failure();
                return {};
            }
            if (count < 0)
                throw std::runtime_error("ROS bridge returned a negative frame size");
            if (opcode == Poco::Net::WebSocket::FRAME_OP_PING)
            {
                _socket->sendFrame(frame.begin(), count,
                    Poco::Net::WebSocket::FRAME_FLAG_FIN |
                    Poco::Net::WebSocket::FRAME_OP_PONG);
                continue;
            }
            if (opcode == Poco::Net::WebSocket::FRAME_OP_PONG)
                continue;
            if (opcode == Poco::Net::WebSocket::FRAME_OP_TEXT)
            {
                if (_receivingTextFragments)
                    throw std::runtime_error("ROS bridge received a new text frame before continuation completed");
                _receiveBuffer.assign(frame.begin(), static_cast<std::size_t>(count));
                _receivingTextFragments =
                    (flags & Poco::Net::WebSocket::FRAME_FLAG_FIN) == 0;
            }
            else if (opcode == Poco::Net::WebSocket::FRAME_OP_CONT)
            {
                if (!_receivingTextFragments)
                    throw std::runtime_error("ROS bridge received an unexpected continuation frame");
                _receiveBuffer.append(frame.begin(), static_cast<std::size_t>(count));
                if ((flags & Poco::Net::WebSocket::FRAME_FLAG_FIN) != 0)
                    _receivingTextFragments = false;
            }
            else
                throw std::runtime_error("ROS bridge only accepts JSON text messages");

            if (_receiveBuffer.size() > _maximumMessageSize)
            {
                _receiveBuffer.clear();
                _receivingTextFragments = false;
                throw std::length_error("ROS bridge message exceeds configured maximum");
            }
            if (!_receivingTextFragments)
            {
                text.swap(_receiveBuffer);
                messageComplete = true;
            }
            }
            handler = _handler;
        }
    }
    catch (const std::exception& error)
    {
        std::lock_guard lock(_mutex);
        ++_diagnostics.failedOperations;
        recordFailure(_diagnostics, _failure, "PDR-PROTOCOL-ROS-RECEIVE_FAILED",
                      Reliability::FailureKind::transient, true, error.what());
        throw;
    }

    try
    {
        Poco::JSON::Parser parser;
        const auto object = parser.parse(text).extract<Poco::JSON::Object::Ptr>();
        if (handler)
        {
            try { handler(object); }
            catch (...)
            {
                std::lock_guard lock(_mutex);
                ++_diagnostics.handlerFailures;
            }
        }
        {
            std::lock_guard lock(_mutex);
            ++_diagnostics.successfulOperations;
            ++_diagnostics.receivedMessages;
            _diagnostics.receivedBytes += text.size();
            resolveFailure(_diagnostics, _failure);
        }
        metric.success();
        return object;
    }
    catch (const std::exception& error)
    {
        std::lock_guard lock(_mutex);
        ++_diagnostics.failedOperations;
        recordFailure(_diagnostics, _failure, "PDR-PROTOCOL-ROS-PAYLOAD_INVALID",
                      Reliability::FailureKind::permanent, false, error.what());
        throw;
    }
}

void BridgeClient::setMessageHandler(MessageHandler handler)
{
    std::lock_guard lock(_mutex);
    _handler = std::move(handler);
}

ProtocolDiagnostics BridgeClient::diagnostics() const
{
    std::lock_guard lock(_mutex);
    return _diagnostics;
}

PocoDDS::Reliability::Failure BridgeClient::failure() const
{
    std::lock_guard lock(_mutex);
    return _failure;
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
    PocoDDS::Protocols::ProtocolMetricTimer metric("rosbridge", "send", payload.size());
    try
    {
        _socket->sendFrame(
            payload.data(),
            static_cast<int>(payload.size()),
            Poco::Net::WebSocket::FRAME_TEXT);
        ++_diagnostics.successfulOperations;
        ++_diagnostics.sentMessages;
        _diagnostics.sentBytes += payload.size();
        resolveFailure(_diagnostics, _failure);
        metric.success();
    }
    catch (const std::exception& error)
    {
        ++_diagnostics.failedOperations;
        recordFailure(_diagnostics, _failure, "PDR-PROTOCOL-ROS-SEND_FAILED",
                      Reliability::FailureKind::transient, true, error.what());
        throw;
    }
}

} // namespace PocoDDS::Protocols::ROS
