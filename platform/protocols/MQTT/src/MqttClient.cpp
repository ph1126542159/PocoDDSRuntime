#include "PocoDDS/Protocols/MQTT/MqttClient.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <chrono>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Protocols::MQTT
{
namespace
{
bool isTlsUri(const std::string& uri)
{
    return uri.rfind("ssl://", 0) == 0 || uri.rfind("wss://", 0) == 0;
}
}

MqttClient::MqttClient(Options options) : _options(std::move(options))
{
    if (_options.serverUri.empty() || _options.clientId.empty())
        throw std::invalid_argument("MQTT server URI and client ID are required");
    if (_options.keepAliveSeconds < 0 || _options.connectTimeoutSeconds <= 0)
        throw std::invalid_argument("MQTT keep-alive must be non-negative and connect timeout positive");
    const bool tls = isTlsUri(_options.serverUri);
    const bool hasTlsMaterial = !_options.trustStore.empty() || !_options.keyStore.empty() ||
                                !_options.privateKey.empty() ||
                                !_options.privateKeyPassword.empty() ||
                                !_options.enabledCipherSuites.empty();
    if (hasTlsMaterial && !tls)
        throw std::invalid_argument("MQTT TLS material requires an ssl:// or wss:// server URI");
    if (!_options.privateKey.empty() && _options.keyStore.empty())
        throw std::invalid_argument("MQTT private key requires a client key store/certificate");
    if (!_options.privateKeyPassword.empty() && _options.privateKey.empty())
        throw std::invalid_argument("MQTT private key password requires a private key");
    requireSuccess(MQTTClient_create(&_client,
                                     _options.serverUri.c_str(),
                                     _options.clientId.c_str(),
                                     MQTTCLIENT_PERSISTENCE_NONE,
                                     nullptr),
                   "create");
    try
    {
        requireSuccess(MQTTClient_setCallbacks(
                           _client, this, &MqttClient::onConnectionLost,
                           &MqttClient::onMessageArrived, &MqttClient::onDeliveryComplete),
                       "set callbacks");
    }
    catch (...)
    {
        MQTTClient_destroy(&_client);
        throw;
    }
}

MqttClient::~MqttClient()
{
    close();
    if (_client)
        MQTTClient_destroy(&_client);
}

std::string MqttClient::name() const
{
    return "mqtt:" + _options.serverUri;
}

void MqttClient::open()
{
    Poco::FastMutex::ScopedLock operationLock(_operationMutex);
    if (_connected && MQTTClient_isConnected(_client))
        return;
    _connected = false;
    PocoDDS::Protocols::ProtocolMetricTimer metric("mqtt", "connect");

    MQTTClient_connectOptions options = MQTTClient_connectOptions_initializer;
    options.keepAliveInterval = _options.keepAliveSeconds;
    options.cleansession = _options.cleanSession ? 1 : 0;
    options.connectTimeout = _options.connectTimeoutSeconds;
    options.username = _options.username.empty() ? nullptr : _options.username.c_str();
    options.password = _options.password.empty() ? nullptr : _options.password.c_str();
    MQTTClient_SSLOptions sslOptions = MQTTClient_SSLOptions_initializer;
    if (isTlsUri(_options.serverUri))
    {
        sslOptions.trustStore = _options.trustStore.empty() ? nullptr : _options.trustStore.c_str();
        sslOptions.keyStore = _options.keyStore.empty() ? nullptr : _options.keyStore.c_str();
        sslOptions.privateKey = _options.privateKey.empty() ? nullptr : _options.privateKey.c_str();
        sslOptions.privateKeyPassword = _options.privateKeyPassword.empty()
            ? nullptr : _options.privateKeyPassword.c_str();
        sslOptions.enabledCipherSuites = _options.enabledCipherSuites.empty()
            ? nullptr : _options.enabledCipherSuites.c_str();
        sslOptions.enableServerCertAuth = _options.verifyServerCertificate ? 1 : 0;
        sslOptions.verify = _options.verifyHostname ? 1 : 0;
        options.ssl = &sslOptions;
    }
    try
    {
        if (_everConnected)
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            ++_diagnostics.reconnectAttempts;
        }
        requireSuccess(MQTTClient_connect(_client, &options), "connect");
        for (const auto& [topic, qos] : _subscriptions)
            requireSuccess(MQTTClient_subscribe(
                               _client, topic.c_str(), static_cast<int>(qos)),
                           "restore subscription");
        _connected = true;
        _intentionalDisconnect = false;
        _everConnected = true;
        markSuccess();
        metric.success();
    }
    catch (const std::exception& error)
    {
        _connected = false;
        if (MQTTClient_isConnected(_client))
        {
            _intentionalDisconnect = true;
            MQTTClient_disconnect(_client, 1000);
        }
        markFailure(error.what());
        throw;
    }
}

void MqttClient::close() noexcept
{
    Poco::FastMutex::ScopedLock operationLock(_operationMutex);
    if (!_connected.exchange(false))
        return;
    _intentionalDisconnect = true;
    _ignoreLossUntilNanoseconds = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch() + std::chrono::seconds(1)).count();
    MQTTClient_disconnect(_client, 3000);
}

bool MqttClient::isOpen() const noexcept
{
    if (!_connected) return false;
    if (MQTTClient_isConnected(_client)) return true;
    _connected = false;
    return false;
}

void MqttClient::publish(const std::string& topic,
                         const std::string& payload,
                         QoS qos,
                         bool retained)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("mqtt", "publish", payload.size());
    if (topic.empty()) throw std::invalid_argument("MQTT publish topic must not be empty");
    Poco::FastMutex::ScopedLock operationLock(_operationMutex);
    if (!_connected) throw std::logic_error("MQTT client is not connected");
    MQTTClient_message message = MQTTClient_message_initializer;
    message.payload = const_cast<char*>(payload.data());
    message.payloadlen = static_cast<int>(payload.size());
    message.qos = static_cast<int>(qos);
    message.retained = retained ? 1 : 0;
    MQTTClient_deliveryToken token = 0;
    try
    {
        requireSuccess(MQTTClient_publishMessage(_client, topic.c_str(), &message, &token), "publish");
        if (qos != QoS::atMostOnce)
            requireSuccess(MQTTClient_waitForCompletion(_client, token, 5000), "wait for delivery");
        markSuccess();
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            ++_diagnostics.sentMessages;
            _diagnostics.sentBytes += payload.size();
        }
        metric.success();
    }
    catch (const std::exception& error)
    {
        markFailure(error.what());
        throw;
    }
}

void MqttClient::subscribe(const std::string& topic, QoS qos)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("mqtt", "subscribe");
    if (topic.empty()) throw std::invalid_argument("MQTT subscription topic must not be empty");
    Poco::FastMutex::ScopedLock operationLock(_operationMutex);
    if (!_connected) throw std::logic_error("MQTT client is not connected");
    try
    {
        requireSuccess(MQTTClient_subscribe(_client, topic.c_str(), static_cast<int>(qos)),
                       "subscribe");
        _subscriptions[topic] = qos;
        markSuccess();
        metric.success();
    }
    catch (const std::exception& error)
    {
        markFailure(error.what());
        throw;
    }
}

void MqttClient::unsubscribe(const std::string& topic)
{
    Poco::FastMutex::ScopedLock operationLock(_operationMutex);
    if (!_connected) throw std::logic_error("MQTT client is not connected");
    try
    {
        requireSuccess(MQTTClient_unsubscribe(_client, topic.c_str()), "unsubscribe");
        _subscriptions.erase(topic);
        markSuccess();
    }
    catch (const std::exception& error)
    {
        markFailure(error.what());
        throw;
    }
}

void MqttClient::setMessageHandler(MessageHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _handler = std::move(handler);
}

void MqttClient::onConnectionLost(void* context, char* cause)
{
    auto* self = static_cast<MqttClient*>(context);
    const auto now = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
    if (self->_intentionalDisconnect || now < self->_ignoreLossUntilNanoseconds)
        return;
    self->_connected = false;
    self->markFailure(std::string("MQTT connection lost") +
                      (cause && *cause ? ": " + std::string(cause) : ""));
}

int MqttClient::onMessageArrived(void* context,
                                 char* topicName,
                                 int topicLength,
                                 MQTTClient_message* message)
{
    auto* self = static_cast<MqttClient*>(context);
    bool success = false;
    std::size_t payloadSize = 0;
    try
    {
        if (!topicName || !message || message->payloadlen < 0)
            throw std::runtime_error("invalid MQTT callback arguments");
        Message value;
        value.topic = topicLength > 0
            ? std::string(topicName, static_cast<std::size_t>(topicLength))
            : std::string(topicName);
        if (message->payloadlen > 0 && !message->payload)
            throw std::runtime_error("invalid MQTT callback payload");
        if (message->payloadlen > 0)
            value.payload.assign(static_cast<const char*>(message->payload),
                                 static_cast<std::size_t>(message->payloadlen));
        payloadSize = value.payload.size();
        value.qos = static_cast<QoS>(message->qos);
        value.retained = message->retained != 0;
        value.duplicate = message->dup != 0;

        MessageHandler handler;
        {
            Poco::FastMutex::ScopedLock lock(self->_mutex);
            handler = self->_handler;
        }
        if (handler)
        {
            try { handler(value); }
            catch (...)
            {
                Poco::FastMutex::ScopedLock lock(self->_mutex);
                ++self->_diagnostics.handlerFailures;
            }
        }
        success = true;
    }
    catch (const std::exception& error)
    {
        self->markFailure(error.what());
    }

    if (message) MQTTClient_freeMessage(&message);
    if (topicName) MQTTClient_free(topicName);
    if (success)
    {
        Poco::FastMutex::ScopedLock lock(self->_mutex);
        ++self->_diagnostics.successfulOperations;
        ++self->_diagnostics.receivedMessages;
        self->_diagnostics.receivedBytes += payloadSize;
        resolveFailure(self->_diagnostics, self->_failure);
    }
    PocoDDS::Protocols::ProtocolMetrics::emit(
        {"mqtt", "receive", success ? "success" : "error", 0, payloadSize});
    return 1;
}

void MqttClient::onDeliveryComplete(void*, MQTTClient_deliveryToken) {}

void MqttClient::requireSuccess(int result, const char* operation)
{
    if (result != MQTTCLIENT_SUCCESS)
        throw std::runtime_error(std::string("MQTT ") + operation +
                                 " failed with code " + std::to_string(result));
}

void MqttClient::markSuccess()
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    ++_diagnostics.successfulOperations;
    resolveFailure(_diagnostics, _failure);
}

void MqttClient::markFailure(const std::string& message)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    ++_diagnostics.failedOperations;
    recordFailure(_diagnostics, _failure, "PDR-PROTOCOL-MQTT-OPERATION_FAILED",
                  Reliability::FailureKind::transient, true, message);
}

ClientDiagnostics MqttClient::diagnostics() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _diagnostics;
}

PocoDDS::Reliability::Failure MqttClient::failure() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _failure;
}
} // namespace PocoDDS::Protocols::MQTT
