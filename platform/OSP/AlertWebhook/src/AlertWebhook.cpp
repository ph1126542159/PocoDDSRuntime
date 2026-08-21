#include "Poco/ClassLibrary.h"
#include "Poco/Environment.h"
#include "Poco/Exception.h"
#include "Poco/JSON/Object.h"
#include "Poco/Net/Context.h"
#include "Poco/Net/HTTPClientSession.h"
#include "Poco/Net/HTTPSClientSession.h"
#include "Poco/Net/HTTPRequest.h"
#include "Poco/Net/HTTPResponse.h"
#include "Poco/Net/PrivateKeyPassphraseHandler.h"
#include "Poco/OSP/BundleActivator.h"
#include "Poco/OSP/BundleContext.h"
#include "Poco/OSP/PreferencesService.h"
#include "Poco/OSP/Properties.h"
#include "Poco/OSP/Service.h"
#include "Poco/OSP/ServiceRef.h"
#include "Poco/OSP/ServiceRegistry.h"
#include "Poco/StreamCopier.h"
#include "Poco/Timespan.h"
#include "Poco/URI.h"
#include "PocoDDS/Reliability/AlertSink.h"
#include "PocoDDS/Configuration/IndexedConfiguration.h"

#include <algorithm>
#include <chrono>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace PocoDDS::AlertWebhook
{
namespace
{
struct Options
{
    std::string url;
    std::string authorization;
    std::string caCertificate;
    std::string clientCertificate;
    std::string privateKey;
    std::string privateKeyPassword;
    bool insecureSkipVerify{false};
    int timeoutMilliseconds{3000};
    int maximumAttempts{3};
    int initialBackoffMilliseconds{200};
    int maximumBackoffMilliseconds{2000};
};

class FixedPassphraseHandler final : public Poco::Net::PrivateKeyPassphraseHandler
{
public:
    explicit FixedPassphraseHandler(std::string passphrase):
        Poco::Net::PrivateKeyPassphraseHandler(false), _passphrase(std::move(passphrase)) {}
    void onPrivateKeyRequested(const void*, std::string& value) override { value = _passphrase; }
private:
    std::string _passphrase;
};

class WebhookSink final : public Poco::OSP::Service,
                          public PocoDDS::Reliability::AlertSink
{
public:
    explicit WebhookSink(Options options): _options(std::move(options)), _uri(_options.url)
    {
        if ((_uri.getScheme() != "http" && _uri.getScheme() != "https") ||
            _uri.getHost().empty())
            throw std::invalid_argument("pdr.alerts.webhook.url must be an HTTP(S) URL");
        if (_options.timeoutMilliseconds <= 0 || _options.maximumAttempts <= 0 ||
            _options.initialBackoffMilliseconds < 0 ||
            _options.maximumBackoffMilliseconds < _options.initialBackoffMilliseconds)
            throw std::invalid_argument("webhook retry and timeout values are invalid");
        if (static_cast<bool>(_options.clientCertificate.empty()) !=
            static_cast<bool>(_options.privateKey.empty()))
            throw std::invalid_argument(
                "webhook clientCertificate and privateKey must be configured together");
        if (_uri.getScheme() != "https" &&
            (!_options.caCertificate.empty() || !_options.clientCertificate.empty() ||
             _options.insecureSkipVerify))
            throw std::invalid_argument("webhook TLS options require an HTTPS URL");
        if (!_options.privateKeyPassword.empty())
            _passphrase = std::make_unique<FixedPassphraseHandler>(_options.privateKeyPassword);
    }

    void deliver(const PocoDDS::Reliability::AlertNotification& notification) override
    {
        const auto body = serialize(notification);
        int delay = _options.initialBackoffMilliseconds;
        std::string lastError;
        for (int attempt = 1; attempt <= _options.maximumAttempts; ++attempt)
        {
            bool retryable = true;
            try
            {
                auto session = createSession();
                Poco::Net::HTTPRequest request(Poco::Net::HTTPRequest::HTTP_POST,
                    _uri.getPathEtc().empty() ? "/" : _uri.getPathEtc(),
                    Poco::Net::HTTPMessage::HTTP_1_1);
                request.setContentType("application/json");
                request.setContentLength(body.size());
                request.set("User-Agent", "PocoDDSRuntime-AlertWebhook/1.0");
                request.set("Idempotency-Key", notification.alertId + ":" + notification.event);
                request.set("X-PDR-Alert-Id", notification.alertId);
                request.set("X-PDR-Trace-Id", notification.traceId);
                if (!_options.authorization.empty())
                    request.set("Authorization", _options.authorization);
                session->sendRequest(request) << body;
                Poco::Net::HTTPResponse response;
                auto& responseStream = session->receiveResponse(response);
                std::string ignored;
                Poco::StreamCopier::copyToString(responseStream, ignored);
                if (response.getStatus() >= 200 && response.getStatus() < 300) return;
                retryable = response.getStatus() == 408 || response.getStatus() == 429 ||
                            response.getStatus() >= 500;
                lastError = "HTTP " + std::to_string(response.getStatus());
            }
            catch (const Poco::Exception& exception)
            {
                lastError = exception.displayText();
            }
            catch (const std::exception& exception)
            {
                lastError = exception.what();
            }
            if (!retryable || attempt == _options.maximumAttempts) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(delay));
            delay = std::min(delay * 2, _options.maximumBackoffMilliseconds);
        }
        throw Poco::IOException("alert webhook delivery failed: " + lastError);
    }

    const std::type_info& type() const override { return typeid(WebhookSink); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(WebhookSink).name() ||
               Poco::OSP::Service::isA(other);
    }

private:
    std::unique_ptr<Poco::Net::HTTPClientSession> createSession() const
    {
        std::unique_ptr<Poco::Net::HTTPClientSession> session;
        if (_uri.getScheme() == "https")
        {
            Poco::Net::Context::Params parameters;
            parameters.caLocation = _options.caCertificate;
            parameters.certificateFile = _options.clientCertificate;
            parameters.privateKeyFile = _options.privateKey;
            parameters.verificationMode = _options.insecureSkipVerify
                ? Poco::Net::Context::VERIFY_NONE : Poco::Net::Context::VERIFY_STRICT;
            parameters.loadDefaultCAs = parameters.caLocation.empty();
            auto context = new Poco::Net::Context(Poco::Net::Context::TLS_CLIENT_USE, parameters);
            context->enableExtendedCertificateVerification(!_options.insecureSkipVerify);
            session = std::make_unique<Poco::Net::HTTPSClientSession>(
                _uri.getHost(), _uri.getPort(), context);
        }
        else
            session = std::make_unique<Poco::Net::HTTPClientSession>(
                _uri.getHost(), _uri.getPort());
        session->setTimeout(Poco::Timespan(
            static_cast<Poco::Int64>(_options.timeoutMilliseconds) * 1000));
        return session;
    }

    static std::string serialize(const PocoDDS::Reliability::AlertNotification& value)
    {
        Poco::JSON::Object object;
        object.set("schemaVersion", 1);
        object.set("alertId", value.alertId);
        object.set("event", value.event);
        object.set("domain", value.domain);
        object.set("instance", value.instance);
        object.set("code", value.code);
        object.set("status", value.status);
        object.set("severity", value.severity);
        object.set("traceId", value.traceId);
        object.set("message", value.message);
        object.set("retryable", value.retryable);
        object.set("silenced", value.silenced);
        object.set("occurredAtMicroseconds", value.occurredAtMicroseconds);
        std::ostringstream output;
        object.stringify(output);
        return output.str();
    }

    Options _options;
    Poco::URI _uri;
    std::unique_ptr<FixedPassphraseHandler> _passphrase;
};

std::string environmentValue(const Poco::Util::AbstractConfiguration& config,
                             const std::string& key)
{
    const auto name = config.getString(key, "");
    if (name.empty()) return {};
    if (!Poco::Environment::has(name) || Poco::Environment::get(name).empty())
        throw std::invalid_argument(key + " references an unset or empty environment variable");
    return Poco::Environment::get(name);
}
}

class BundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        auto preferences = context->registry()
            .findByName(Poco::OSP::PreferencesService::SERVICE_NAME)
            ->castedInstance<Poco::OSP::PreferencesService>();
        auto config = preferences->configuration();
        const auto instances = PocoDDS::Configuration::indexedInstances(
            *config, "pdr.alerts.webhook", false, 0, "webhook");
        std::size_t registered = 0;
        for (const auto& instance : instances)
        {
            if (!instance.enabled) continue;
            const auto& prefix = instance.prefix;
            Options options;
            options.url = config->getString(prefix + ".url", "");
            options.authorization = environmentValue(
                *config, prefix + ".authorizationEnvironment");
            options.caCertificate = config->getString(prefix + ".caCertificate", "");
            options.clientCertificate = config->getString(prefix + ".clientCertificate", "");
            options.privateKey = config->getString(prefix + ".privateKey", "");
            options.privateKeyPassword = environmentValue(
                *config, prefix + ".privateKeyPasswordEnvironment");
            options.insecureSkipVerify = config->getBool(
                prefix + ".insecureSkipVerify", false);
            options.timeoutMilliseconds = config->getInt(
                prefix + ".timeoutMilliseconds", 3000);
            options.maximumAttempts = config->getInt(
                prefix + ".maximumAttempts", 3);
            options.initialBackoffMilliseconds = config->getInt(
                prefix + ".initialBackoffMilliseconds", 200);
            options.maximumBackoffMilliseconds = config->getInt(
                prefix + ".maximumBackoffMilliseconds", 2000);
            Poco::AutoPtr<WebhookSink> sink = new WebhookSink(std::move(options));
            Poco::OSP::Properties properties;
            properties.set("pdr.alertSink", "true");
            properties.set("pdr.alertSink.name", instance.legacy ? "webhook" : instance.id);
            properties.set("pdr.alertSink.type", "https-webhook");
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            const auto serviceName = instance.legacy
                ? "pdr.alertSink.webhook" : "pdr.alertSink.webhook." + instance.id;
            _services.push_back(
                context->registry().registerService(serviceName, sink, properties));
            _sinks.push_back(std::move(sink));
            ++registered;
        }
        if (registered)
            context->logger().information(
                "Alert webhook sink registered: " + std::to_string(registered) + " instance(s).");
        else
            context->logger().information("Alert webhook sink disabled.");
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        for (const auto& service : _services)
            if (service) context->registry().unregisterService(service);
        _services.clear();
        _sinks.clear();
    }

private:
    std::vector<Poco::AutoPtr<WebhookSink>> _sinks;
    std::vector<Poco::OSP::ServiceRef::Ptr> _services;
};
}

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::AlertWebhook::BundleActivator)
POCO_END_MANIFEST
