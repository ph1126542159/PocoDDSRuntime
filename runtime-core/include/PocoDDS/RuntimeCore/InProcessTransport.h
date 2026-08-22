#pragma once

#include "PocoDDS/RuntimeCore/Transport.h"

#include <memory>

namespace PocoDDS::RuntimeCore
{

class PDR_RUNTIME_CORE_API InProcessTransport final: public IMessageTransport
{
public:
    InProcessTransport();
    ~InProcessTransport() override;

    InProcessTransport(const InProcessTransport&) = delete;
    InProcessTransport& operator=(const InProcessTransport&) = delete;

    std::string id() const override;
    TransportCapabilities capabilities() const noexcept override;
    Subscription subscribe(const TopicSpec& topic, Handler handler) override;
    PublishResult publish(const TopicSpec& topic, const Message& message) override;
    std::size_t subscriptionCount() const noexcept;

private:
    struct State;
    std::shared_ptr<State> _state;
};

} // namespace PocoDDS::RuntimeCore
