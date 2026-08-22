#pragma once

#include "PocoDDS/MqttTransport/Export.h"
#include "PocoDDS/RuntimeCore/Codec.h"
#include "PocoDDS/RuntimeCore/InProcessTransport.h"

#include <memory>
#include <string>

namespace PocoDDS::MqttTransport
{

struct MqttTransportOptions
{
    std::string serverUri;
    std::string clientId;
    std::string topicPrefix{"pdr/"};
    std::string username;
    std::string password;
    std::string trustStore;
    std::string keyStore;
    std::string privateKey;
    std::string privateKeyPassword;
    std::string enabledCipherSuites;
    bool verifyServerCertificate{true};
    bool verifyHostname{true};
    bool cleanSession{true};
    int keepAliveSeconds{30};
    int connectTimeoutSeconds{10};
    PocoDDS::RuntimeCore::MessageCodecLimits codecLimits;
};

class PDR_MQTT_TRANSPORT_API MqttTransport final : public PocoDDS::RuntimeCore::IMessageTransport
{
  public:
    explicit MqttTransport(MqttTransportOptions options);
    ~MqttTransport() override;

    MqttTransport(const MqttTransport&) = delete;
    MqttTransport& operator=(const MqttTransport&) = delete;

    PocoDDS::RuntimeCore::Outcome<void> start();
    void stop() noexcept;
    bool running() const noexcept;

    std::string id() const override;
    PocoDDS::RuntimeCore::TransportCapabilities capabilities() const noexcept override;
    PocoDDS::RuntimeCore::Subscription subscribe(const PocoDDS::RuntimeCore::TopicSpec& topic,
                                                 Handler handler) override;
    PocoDDS::RuntimeCore::PublishResult
    publish(const PocoDDS::RuntimeCore::TopicSpec& topic,
            const PocoDDS::RuntimeCore::Message& message) override;

  private:
    struct State;
    std::shared_ptr<State> _state;
};

} // namespace PocoDDS::MqttTransport
