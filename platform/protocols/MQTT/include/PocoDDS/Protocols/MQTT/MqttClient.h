#pragma once

#include "PocoDDS/Protocols/Protocol.h"
#include "PocoDDS/Protocols/ProtocolDiagnostics.h"

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

using ClientDiagnostics = PocoDDS::Protocols::ProtocolDiagnostics;

class MqttClient final : public PocoDDS::Protocols::DiagnosticProtocol,
                         public PocoDDS::Protocols::FailureDiagnosticProtocol
{
public:
    struct Options
    {
        std::string serverUri;
        std::string clientId;
        std::string username;
        std::string password;
        std::string trustStore;
        std::string keyStore;
        std::string privateKey;
        std::string privateKeyPassword;
        std::string enabledCipherSuites;
        bool verifyServerCertificate{true};
        bool verifyHostname{true};
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
    ClientDiagnostics diagnostics() const override;
    PocoDDS::Reliability::Failure failure() const override;

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
    mutable std::atomic<bool> _connected{false};
    std::atomic<bool> _intentionalDisconnect{false};
    std::atomic<std::int64_t> _ignoreLossUntilNanoseconds{0};
    bool _everConnected{false};
    mutable Poco::FastMutex _operationMutex;
    mutable Poco::FastMutex _mutex;
    MessageHandler _handler;
    std::map<std::string, QoS> _subscriptions;
    ClientDiagnostics _diagnostics;
    PocoDDS::Reliability::Failure _failure;
};
} // namespace PocoDDS::Protocols::MQTT
