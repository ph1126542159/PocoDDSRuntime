#include "PocoDDS/Protocols/WebTunnel/LocalForwarder.h"

#include <Poco/Net/Context.h>
#include <Poco/Net/HTTPClientSession.h>
#include <Poco/Net/HTTPSClientSession.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/Net/SocketAddress.h>
#include <Poco/Net/TCPServerParams.h>
#include <Poco/Net/WebSocket.h>
#include <Poco/Timespan.h>
#include <Poco/URI.h>
#include <Poco/WebTunnel/LocalPortForwarder.h>

#include <memory>
#include <mutex>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Protocols::WebTunnel
{
namespace
{
class ConfiguredWebSocketFactory final : public Poco::WebTunnel::WebSocketFactory
{
public:
    explicit ConfiguredWebSocketFactory(const LocalForwarder::Options& options):
        _options(options)
    {
    }

    Poco::Net::WebSocket* createWebSocket(
        const Poco::URI& uri,
        Poco::Net::HTTPRequest& request,
        Poco::Net::HTTPResponse& response) override
    {
        std::unique_ptr<Poco::Net::HTTPClientSession> session;
        if (uri.getScheme() == "wss")
        {
            Poco::Net::Context::Params parameters;
            parameters.caLocation = _options.trustStore;
            parameters.certificateFile = _options.clientCertificate;
            parameters.privateKeyFile = _options.privateKey;
            parameters.verificationMode = _options.verifyServerCertificate
                ? Poco::Net::Context::VERIFY_STRICT
                : Poco::Net::Context::VERIFY_NONE;
            parameters.loadDefaultCAs = _options.trustStore.empty();
            Poco::Net::Context::Ptr context = new Poco::Net::Context(
                Poco::Net::Context::TLS_CLIENT_USE, parameters);
            context->enableExtendedCertificateVerification(
                _options.verifyServerCertificate && _options.verifyHostname);
            session = std::make_unique<Poco::Net::HTTPSClientSession>(
                uri.getHost(), uri.getPort(), context);
        }
        else
        {
            session = std::make_unique<Poco::Net::HTTPClientSession>(
                uri.getHost(), uri.getPort());
        }
        session->setTimeout(Poco::Timespan(_options.connectTimeoutSeconds, 0));
        if (!_options.authorization.empty())
            request.set("Authorization", _options.authorization);
        return new Poco::Net::WebSocket(*session, request, response);
    }

private:
    LocalForwarder::Options _options;
};

void validate(const LocalForwarder::Options& options)
{
    Poco::URI uri(options.remoteUri);
    if (uri.getScheme() != "ws" && uri.getScheme() != "wss")
        throw std::invalid_argument("WebTunnel remoteUri must use ws or wss");
    if (uri.getHost().empty())
        throw std::invalid_argument("WebTunnel remoteUri must include a host");
    if (options.remotePort == 0)
        throw std::invalid_argument("WebTunnel remotePort must be non-zero");
    if (options.localHost.empty())
        throw std::invalid_argument("WebTunnel localHost must not be empty");
    if (options.connectTimeoutSeconds <= 0 ||
        options.localIdleTimeoutSeconds < 0 ||
        options.remoteIdleTimeoutSeconds <= 0)
        throw std::invalid_argument("WebTunnel timeouts are outside the valid range");
    if (options.maximumQueuedConnections <= 0 || options.maximumThreads <= 0)
        throw std::invalid_argument("WebTunnel connection limits must be positive");
    if (static_cast<bool>(options.clientCertificate.empty()) !=
        static_cast<bool>(options.privateKey.empty()))
        throw std::invalid_argument(
            "WebTunnel clientCertificate and privateKey must be configured together");
    const bool hasTlsMaterial = !options.trustStore.empty() ||
        !options.clientCertificate.empty() || !options.privateKey.empty();
    if (uri.getScheme() != "wss" && hasTlsMaterial)
        throw std::invalid_argument("WebTunnel TLS material requires wss");
}
} // namespace

class LocalForwarder::Impl
{
public:
    explicit Impl(Options options): options(std::move(options)) { validate(this->options); }

    Options options;
    mutable std::mutex mutex;
    std::unique_ptr<Poco::WebTunnel::LocalPortForwarder> forwarder;
};

LocalForwarder::LocalForwarder(Options options):
    _impl(std::make_unique<Impl>(std::move(options)))
{
}

LocalForwarder::~LocalForwarder()
{
    close();
}

void LocalForwarder::open()
{
    std::lock_guard lock(_impl->mutex);
    if (_impl->forwarder) return;
    Poco::Net::TCPServerParams::Ptr serverParameters = new Poco::Net::TCPServerParams;
    serverParameters->setMaxQueued(_impl->options.maximumQueuedConnections);
    serverParameters->setMaxThreads(_impl->options.maximumThreads);
    Poco::WebTunnel::WebSocketFactory::Ptr factory =
        new ConfiguredWebSocketFactory(_impl->options);
    auto forwarder = std::make_unique<Poco::WebTunnel::LocalPortForwarder>(
        Poco::Net::SocketAddress(_impl->options.localHost, _impl->options.localPort),
        _impl->options.remotePort,
        Poco::URI(_impl->options.remoteUri),
        serverParameters,
        factory);
    forwarder->setLocalTimeout(Poco::Timespan(_impl->options.localIdleTimeoutSeconds, 0));
    forwarder->setRemoteTimeout(Poco::Timespan(_impl->options.remoteIdleTimeoutSeconds, 0));
    _impl->forwarder = std::move(forwarder);
}

void LocalForwarder::close() noexcept
{
    std::unique_ptr<Poco::WebTunnel::LocalPortForwarder> forwarder;
    {
        std::lock_guard lock(_impl->mutex);
        forwarder = std::move(_impl->forwarder);
    }
}

bool LocalForwarder::isOpen() const noexcept
{
    std::lock_guard lock(_impl->mutex);
    return static_cast<bool>(_impl->forwarder);
}

std::uint16_t LocalForwarder::localPort() const noexcept
{
    std::lock_guard lock(_impl->mutex);
    return _impl->forwarder ? _impl->forwarder->localPort() : _impl->options.localPort;
}

} // namespace PocoDDS::Protocols::WebTunnel
