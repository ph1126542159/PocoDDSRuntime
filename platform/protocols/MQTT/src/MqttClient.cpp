#include "PocoDDS/Protocols/MQTT/MqttClient.h"

#include <stdexcept>
#include <utility>

namespace PocoDDS::Protocols::MQTT
{
MqttClient::MqttClient(Options options) : _options(std::move(options))
{
    if (_options.serverUri.empty() || _options.clientId.empty())
        throw std::invalid_argument("MQTT server URI and client ID are required");
    requireSuccess(MQTTClient_create(&_client,
                                     _options.serverUri.c_str(),
                                     _options.clientId.c_str(),
                                     MQTTCLIENT_PERSISTENCE_NONE,
                                     nullptr),
                   "create");
    requireSuccess(MQTTClient_setCallbacks(
                       _client, this, &MqttClient::onConnectionLost,
                       &MqttClient::onMessageArrived, &MqttClient::onDeliveryComplete),
                   "set callbacks");
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
    Poco::FastMutex::ScopedLock lock(_mutex);
    if (_connected)
        return;

    MQTTClient_connectOptions options = MQTTClient_connectOptions_initializer;
    options.keepAliveInterval = _options.keepAliveSeconds;
    options.cleansession = _options.cleanSession ? 1 : 0;
    options.connectTimeout = _options.connectTimeoutSeconds;
    options.username = _options.username.empty() ? nullptr : _options.username.c_str();
    options.password = _options.password.empty() ? nullptr : _options.password.c_str();
    requireSuccess(MQTTClient_connect(_client, &options), "connect");
    _connected = true;
}

void MqttClient::close() noexcept
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    if (!_connected.exchange(false))
        return;
    MQTTClient_disconnect(_client, 3000);
}

bool MqttClient::isOpen() const noexcept
{
    return _connected;
}

void MqttClient::publish(const std::string& topic,
                         const std::string& payload,
                         QoS qos,
                         bool retained)
{
    if (!_connected)
        throw std::logic_error("MQTT client is not connected");
    MQTTClient_message message = MQTTClient_message_initializer;
    message.payload = const_cast<char*>(payload.data());
    message.payloadlen = static_cast<int>(payload.size());
    message.qos = static_cast<int>(qos);
    message.retained = retained ? 1 : 0;
    MQTTClient_deliveryToken token = 0;
    requireSuccess(MQTTClient_publishMessage(_client, topic.c_str(), &message, &token), "publish");
    if (qos != QoS::atMostOnce)
        requireSuccess(MQTTClient_waitForCompletion(_client, token, 5000), "wait for delivery");
}

void MqttClient::subscribe(const std::string& topic, QoS qos)
{
    if (!_connected)
        throw std::logic_error("MQTT client is not connected");
    requireSuccess(MQTTClient_subscribe(_client, topic.c_str(), static_cast<int>(qos)),
                   "subscribe");
}

void MqttClient::unsubscribe(const std::string& topic)
{
    if (!_connected)
        throw std::logic_error("MQTT client is not connected");
    requireSuccess(MQTTClient_unsubscribe(_client, topic.c_str()), "unsubscribe");
}

void MqttClient::setMessageHandler(MessageHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _handler = std::move(handler);
}

void MqttClient::onConnectionLost(void* context, char*)
{
    static_cast<MqttClient*>(context)->_connected = false;
}

int MqttClient::onMessageArrived(void* context,
                                 char* topicName,
                                 int topicLength,
                                 MQTTClient_message* message)
{
    auto* self = static_cast<MqttClient*>(context);
    Message value;
    value.topic = topicLength > 0 ? std::string(topicName, topicLength) : std::string(topicName);
    value.payload.assign(static_cast<const char*>(message->payload),
                         static_cast<std::size_t>(message->payloadlen));
    value.qos = static_cast<QoS>(message->qos);
    value.retained = message->retained != 0;
    value.duplicate = message->dup != 0;

    MessageHandler handler;
    {
        Poco::FastMutex::ScopedLock lock(self->_mutex);
        handler = self->_handler;
    }
    if (handler)
        handler(value);

    MQTTClient_freeMessage(&message);
    MQTTClient_free(topicName);
    return 1;
}

void MqttClient::onDeliveryComplete(void*, MQTTClient_deliveryToken) {}

void MqttClient::requireSuccess(int result, const char* operation)
{
    if (result != MQTTCLIENT_SUCCESS)
        throw std::runtime_error(std::string("MQTT ") + operation +
                                 " failed with code " + std::to_string(result));
}
} // namespace PocoDDS::Protocols::MQTT
