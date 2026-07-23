#pragma once

#include "PocoDDS/Protocols/Protocol.h"

#include "Poco/Mutex.h"

#include <MQTTClient.h>

#include <atomic>
#include <functional>
#include <string>

namespace PocoDDS::Protocols::MQTT
{
enum class QoS
{
    atMostOnce = 0,
    atLeastOnce = 1,
    exactlyOnce = 2
};

struct Message
{
    std::string topic;
    std::string payload;
    QoS qos{QoS::atMostOnce};
    bool retained{false};
    bool duplicate{false};
};

class MqttClient final : public PocoDDS::Protocols::Protocol
{
public:
    struct Options
    {
        std::string serverUri;
        std::string clientId;
        std::string username;
        std::string password;
        int keepAliveSeconds{30};
        bool cleanSession{true};
        int connectTimeoutSeconds{10};
    };

    using MessageHandler = std::function<void(const Message&)>;

    explicit MqttClient(Options options);
    ~MqttClient() override;

    std::string name() const override;
    void open() override;
    void close() noexcept override;
    bool isOpen() const noexcept override;

    void publish(const std::string& topic,
                 const std::string& payload,
                 QoS qos = QoS::atLeastOnce,
                 bool retained = false);
    void subscribe(const std::string& topic, QoS qos = QoS::atLeastOnce);
    void unsubscribe(const std::string& topic);
    void setMessageHandler(MessageHandler handler);

private:
    static void onConnectionLost(void* context, char* cause);
    static int onMessageArrived(void* context,
                                char* topicName,
                                int topicLength,
                                MQTTClient_message* message);
    static void onDeliveryComplete(void* context, MQTTClient_deliveryToken token);
    static void requireSuccess(int result, const char* operation);

    Options _options;
    MQTTClient _client{nullptr};
    std::atomic<bool> _connected{false};
    mutable Poco::FastMutex _mutex;
    MessageHandler _handler;
};
} // namespace PocoDDS::Protocols::MQTT
