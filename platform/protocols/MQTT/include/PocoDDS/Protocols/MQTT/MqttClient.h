#pragma once

#include "PocoDDS/Protocols/Protocol.h"

#include "Poco/Mutex.h"

#include <MQTTClient.h>

#include <atomic>
#include <cstdint>
#include <functional>
#include <map>
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

struct ClientDiagnostics
{
    std::uint64_t successfulOperations{0};
    std::uint64_t failedOperations{0};
    std::uint64_t reconnectAttempts{0};
    std::uint64_t receivedMessages{0};
    std::uint64_t handlerFailures{0};
    std::string lastError;
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
    ClientDiagnostics diagnostics() const;

private:
    static void onConnectionLost(void* context, char* cause);
    static int onMessageArrived(void* context,
                                char* topicName,
                                int topicLength,
                                MQTTClient_message* message);
    static void onDeliveryComplete(void* context, MQTTClient_deliveryToken token);
    static void requireSuccess(int result, const char* operation);
    void markSuccess();
    void markFailure(const std::string& message);

    Options _options;
    MQTTClient _client{nullptr};
    std::atomic<bool> _connected{false};
    bool _everConnected{false};
    mutable Poco::FastMutex _operationMutex;
    mutable Poco::FastMutex _mutex;
    MessageHandler _handler;
    std::map<std::string, QoS> _subscriptions;
    ClientDiagnostics _diagnostics;
};
} // namespace PocoDDS::Protocols::MQTT
