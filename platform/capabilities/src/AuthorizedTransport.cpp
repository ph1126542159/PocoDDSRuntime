#include "PocoDDS/Capabilities/AuthorizedTransport.h"

#include <Poco/Exception.h>

#include <utility>

namespace PocoDDS::Capabilities
{
namespace
{
AuthorizedTransport::Authorizer leasedAuthorizer(
    std::shared_ptr<DecisionLeaseAuthorizer> authorizer)
{
    if (!authorizer)
        throw Poco::InvalidArgumentException("Decision lease authorizer is required");
    return [authorizer = std::move(authorizer)](const Request& request) {
        return authorizer->authorize(request);
    };
}
} // namespace

AuthorizedTransport::AuthorizedTransport(
    std::string principal, std::shared_ptr<PocoDDS::RuntimeCore::IMessageTransport> transport,
    Authorizer authorizer)
    : _principal(std::move(principal)), _transport(std::move(transport)),
      _authorizer(std::move(authorizer))
{
    if (_principal.empty()) throw Poco::InvalidArgumentException("Transport principal cannot be empty");
    if (!_transport) throw Poco::InvalidArgumentException("Authorized transport delegate is required");
    if (!_authorizer) throw Poco::InvalidArgumentException("Authorized transport authorizer is required");
}

AuthorizedTransport::AuthorizedTransport(
    std::string principal, std::shared_ptr<PocoDDS::RuntimeCore::IMessageTransport> transport,
    std::shared_ptr<DecisionLeaseAuthorizer> authorizer)
    : AuthorizedTransport(std::move(principal), std::move(transport),
                          leasedAuthorizer(std::move(authorizer))) {}

std::string AuthorizedTransport::id() const { return "authorized:" + _transport->id(); }

PocoDDS::RuntimeCore::TransportCapabilities AuthorizedTransport::capabilities() const noexcept
{
    return _transport->capabilities();
}

void AuthorizedTransport::require(const PocoDDS::RuntimeCore::TopicSpec& topic, Action action) const
{
    const auto decision = _authorizer({_principal, ResourceKind::topic, topic.name, action});
    if (!decision.allowed)
        throw Poco::NoPermissionException(decision.code, decision.explanation);
}

PocoDDS::RuntimeCore::Subscription AuthorizedTransport::subscribe(
    const PocoDDS::RuntimeCore::TopicSpec& topic, Handler handler)
{
    require(topic, Action::subscribe);
    return _transport->subscribe(topic, std::move(handler));
}

PocoDDS::RuntimeCore::PublishResult AuthorizedTransport::publish(
    const PocoDDS::RuntimeCore::TopicSpec& topic,
    const PocoDDS::RuntimeCore::Message& message)
{
    require(topic, Action::publish);
    return _transport->publish(topic, message);
}
} // namespace PocoDDS::Capabilities
