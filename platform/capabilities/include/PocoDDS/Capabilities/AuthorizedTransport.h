#pragma once

#include "PocoDDS/Capabilities/DecisionLease.h"
#include "PocoDDS/RuntimeCore/Transport.h"

#include <functional>
#include <memory>

namespace PocoDDS::Capabilities
{
class PDR_CAPABILITIES_API AuthorizedTransport final
    : public PocoDDS::RuntimeCore::IMessageTransport
{
public:
    using Authorizer = std::function<Decision(const Request&)>;

    AuthorizedTransport(std::string principal,
                        std::shared_ptr<PocoDDS::RuntimeCore::IMessageTransport> transport,
                        Authorizer authorizer);
    AuthorizedTransport(std::string principal,
                        std::shared_ptr<PocoDDS::RuntimeCore::IMessageTransport> transport,
                        std::shared_ptr<DecisionLeaseAuthorizer> authorizer);

    std::string id() const override;
    PocoDDS::RuntimeCore::TransportCapabilities capabilities() const noexcept override;
    PocoDDS::RuntimeCore::Subscription subscribe(
        const PocoDDS::RuntimeCore::TopicSpec& topic, Handler handler) override;
    PocoDDS::RuntimeCore::PublishResult publish(
        const PocoDDS::RuntimeCore::TopicSpec& topic,
        const PocoDDS::RuntimeCore::Message& message) override;

private:
    void require(const PocoDDS::RuntimeCore::TopicSpec& topic, Action action) const;

    std::string _principal;
    std::shared_ptr<PocoDDS::RuntimeCore::IMessageTransport> _transport;
    Authorizer _authorizer;
};
} // namespace PocoDDS::Capabilities
