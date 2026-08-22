#pragma once

#include "PocoDDS/FastDdsTransport/Export.h"
#include "PocoDDS/RuntimeCore/Codec.h"
#include "PocoDDS/RuntimeCore/InProcessTransport.h"

#include <cstdint>
#include <memory>
#include <string>

namespace PocoDDS::FastDdsTransport
{

struct FastDdsTransportOptions
{
    std::uint32_t domainId{0};
    std::string participantName{"pdr-runtime-core"};
    std::string topicPrefix{"pdr.runtime."};
    PocoDDS::RuntimeCore::MessageCodecLimits codecLimits{180U * 1024U};
};

class PDR_FASTDDS_TRANSPORT_API FastDdsTransport final
    : public PocoDDS::RuntimeCore::IMessageTransport
{
  public:
    explicit FastDdsTransport(FastDdsTransportOptions options = {});
    ~FastDdsTransport() override;

    FastDdsTransport(const FastDdsTransport&) = delete;
    FastDdsTransport& operator=(const FastDdsTransport&) = delete;

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

} // namespace PocoDDS::FastDdsTransport
