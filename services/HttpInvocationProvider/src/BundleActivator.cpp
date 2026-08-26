#include "PocoDDS/ServiceClient/HttpInvocationProvider.h"
#include "PocoDDS/Health/Health.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Environment.h>
#include <Poco/NumberParser.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/Service.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/StringTokenizer.h>
#include <Poco/Util/AbstractConfiguration.h>

#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::ServiceClient
{
namespace
{
constexpr const char* PREFIX = "pdr.serviceClient.httpProvider";

std::vector<std::string> strings(const std::string& value)
{
    Poco::StringTokenizer tokens(value, ",",
        Poco::StringTokenizer::TOK_TRIM |
        Poco::StringTokenizer::TOK_IGNORE_EMPTY);
    return {tokens.begin(), tokens.end()};
}

std::vector<std::uint16_t> ports(const std::string& value)
{
    std::vector<std::uint16_t> result;
    for (const auto& token : strings(value))
    {
        const auto parsed = Poco::NumberParser::parseUnsigned(token);
        if (parsed == 0 || parsed > 65535)
            throw std::invalid_argument(
                "pdr.serviceClient.httpProvider.allowedPorts contains an invalid port");
        result.push_back(static_cast<std::uint16_t>(parsed));
    }
    return result;
}

std::string environmentValue(
    const Poco::Util::AbstractConfiguration& configuration,
    const std::string& key)
{
    const auto name = configuration.getString(key, "");
    if (name.empty()) return {};
    if (!Poco::Environment::has(name) || Poco::Environment::get(name).empty())
        throw std::invalid_argument(
            key + " references an unset or empty environment variable");
    return Poco::Environment::get(name);
}

std::vector<HttpAuthorizationRule> authorizationRules(
    const Poco::Util::AbstractConfiguration& configuration)
{
    const auto count = configuration.getUInt(
        std::string(PREFIX) + ".credentials.count", 0);
    if (count > 256)
        throw std::invalid_argument(
            "pdr.serviceClient.httpProvider.credentials.count exceeds 256");
    std::vector<HttpAuthorizationRule> result;
    result.reserve(count);
    for (unsigned index = 0; index < count; ++index)
    {
        const auto base = std::string(PREFIX) + ".credentials." +
            std::to_string(index) + ".";
        HttpAuthorizationRule rule;
        rule.service = configuration.getString(base + "service");
        rule.operation = configuration.getString(base + "operation");
        rule.host = configuration.getString(base + "host");
        const auto port = configuration.getUInt(base + "port", 0);
        if (port > 65535)
            throw std::invalid_argument(base + "port is invalid");
        rule.port = static_cast<std::uint16_t>(port);
        const auto environment = configuration.getString(
            base + "authorizationEnvironment", "");
        const auto file = configuration.getString(
            base + "authorizationFile", "");
        if (environment.empty() == file.empty())
            throw std::invalid_argument(
                base + " requires exactly one authorizationEnvironment or authorizationFile");
        if (!environment.empty())
            rule.authorization = environmentValue(
                configuration, base + "authorizationEnvironment");
        else
            rule.authorizationFile = configuration.expand(file);
        result.push_back(std::move(rule));
    }
    return result;
}
} // namespace

class HttpInvocationProviderHealth final : public Poco::OSP::Service,
                                           public Health::IHealthContributor
{
public:
    using Ptr = Poco::AutoPtr<HttpInvocationProviderHealth>;

    explicit HttpInvocationProviderHealth(
        const std::vector<Poco::AutoPtr<HttpInvocationProvider>>* providers)
        : _providers(providers)
    {
    }

    Health::Report health() const override
    {
        std::size_t fileBackedRules = 0;
        std::uint64_t generation = 0;
        std::uint64_t reloads = 0;
        std::uint64_t failures = 0;
        bool healthy = true;
        std::vector<std::string> affected;
        if (_providers)
        {
            for (const auto& provider : *_providers)
            {
                const auto snapshot = provider->credentialSnapshot();
                fileBackedRules += snapshot.fileBackedRules;
                generation += snapshot.generation;
                reloads += snapshot.reloads;
                failures += snapshot.reloadFailures;
                if (!snapshot.healthy)
                {
                    healthy = false;
                    affected.push_back(provider->providerId());
                }
            }
        }
        if (!healthy)
            return {"http-invocation-credentials", Health::Status::degraded,
                    std::to_string(failures) +
                        " credential reload failure(s); current calls fail closed",
                    "PDR-HEALTH-HTTP-CREDENTIAL-RELOAD-FAILED",
                    "Atomically replace the credential file with a non-empty, "
                    "single-line value and restricted permissions.",
                    std::move(affected)};
        return {"http-invocation-credentials", Health::Status::up,
                std::to_string(fileBackedRules) +
                    " file-backed rule(s), generation " +
                    std::to_string(generation) + ", " +
                    std::to_string(reloads) + " successful reload(s)",
                "PDR-HEALTH-HTTP-CREDENTIALS-UP", "", {}};
    }

    const std::type_info& type() const override
    {
        return typeid(HttpInvocationProviderHealth);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) ==
                   typeid(HttpInvocationProviderHealth).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~HttpInvocationProviderHealth() override = default;

private:
    const std::vector<Poco::AutoPtr<HttpInvocationProvider>>* _providers;
};

class HttpInvocationProviderBundleActivator final :
    public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        auto preferences = Poco::OSP::ServiceFinder::find<
            Poco::OSP::PreferencesService>(context);
        auto configuration = preferences->configuration();
        if (!configuration->getBool(std::string(PREFIX) + ".enabled", false))
        {
            context->logger().information(
                "HTTP invocation Provider disabled by configuration.");
            return;
        }

        HttpInvocationOptions base;
        base.allowedHosts = strings(configuration->getString(
            std::string(PREFIX) + ".allowedHosts", ""));
        base.allowedPorts = ports(configuration->getString(
            std::string(PREFIX) + ".allowedPorts", "443"));
        base.allowLoopback = configuration->getBool(
            std::string(PREFIX) + ".allowLoopback", false);
        base.allowPrivateNetworks = configuration->getBool(
            std::string(PREFIX) + ".allowPrivateNetworks", false);
        base.allowLinkLocal = configuration->getBool(
            std::string(PREFIX) + ".allowLinkLocal", false);
        base.maximumRequestBytes = static_cast<std::size_t>(
            configuration->getUInt64(
                std::string(PREFIX) + ".maximumRequestBytes", 1024 * 1024));
        base.maximumResponseBytes = static_cast<std::size_t>(
            configuration->getUInt64(
                std::string(PREFIX) + ".maximumResponseBytes", 1024 * 1024));
        base.maximumTimeout = std::chrono::milliseconds(
            configuration->getUInt(
                std::string(PREFIX) + ".maximumTimeoutMilliseconds", 5000));
        base.caCertificate = configuration->getString(
            std::string(PREFIX) + ".caCertificate", "");
        base.authorization = environmentValue(
            *configuration,
            std::string(PREFIX) + ".authorizationEnvironment");
        base.authorizationRules = authorizationRules(*configuration);
        base.requireAuthorizationMatch = configuration->getBool(
            std::string(PREFIX) + ".credentials.required", false);
        base.requireRestrictedCredentialFiles = configuration->getBool(
            std::string(PREFIX) +
                ".credentials.requireRestrictedFiles", true);
        base.credentialReloadInterval = std::chrono::milliseconds(
            configuration->getUInt(
                std::string(PREFIX) +
                    ".credentials.reloadIntervalMilliseconds", 1000));

        auto https = base;
        https.providerId = "builtin-https";
        https.protocol = "https";
        registerProvider(context, std::move(https));

        if (configuration->getBool(
                std::string(PREFIX) + ".allowPlainHttp", false))
        {
            auto http = base;
            http.providerId = "builtin-http";
            http.protocol = "http";
            http.caCertificate.clear();
            registerProvider(context, std::move(http));
        }
        _health = new HttpInvocationProviderHealth(&_providers);
        Poco::OSP::Properties healthProperties;
        healthProperties.set("pdr.bundle",
                             context->thisBundle()->symbolicName());
        healthProperties.set("pdr.healthContributor", "true");
        healthProperties.set("pdr.healthContributor.component",
                             "http-invocation-credentials");
        _healthRef = context->registry().registerService(
            "pdr.healthContributor.httpInvocationCredentials", _health,
            healthProperties);
        context->logger().information(
            "HTTP invocation Provider started with explicit egress policy and " +
            std::to_string(_providers.size()) + " protocol registration(s).");
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_healthRef)
        {
            try { context->registry().unregisterService(_healthRef); }
            catch (...) {}
        }
        _healthRef = nullptr;
        _health = nullptr;
        for (auto iterator = _references.rbegin();
             iterator != _references.rend(); ++iterator)
        {
            try { context->registry().unregisterService(*iterator); }
            catch (...) {}
        }
        _references.clear();
        _providers.clear();
    }

private:
    void registerProvider(Poco::OSP::BundleContext::Ptr context,
                          HttpInvocationOptions options)
    {
        Poco::AutoPtr<HttpInvocationProvider> provider =
            new HttpInvocationProvider(std::move(options));
        Poco::OSP::Properties properties;
        properties.set(ServiceInvocationProvider::PROPERTY_KIND,
                       ServiceInvocationProvider::KIND);
        properties.set(ServiceInvocationProvider::PROPERTY_ID,
                       provider->providerId());
        properties.set(ServiceInvocationProvider::PROPERTY_PROTOCOL,
                       provider->protocol());
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        const auto serviceName =
            "pdr.serviceInvocation.provider." + provider->protocol();
        _references.push_back(context->registry().registerService(
            serviceName, provider, properties));
        _providers.push_back(std::move(provider));
    }

    std::vector<Poco::OSP::ServiceRef::Ptr> _references;
    std::vector<Poco::AutoPtr<HttpInvocationProvider>> _providers;
    HttpInvocationProviderHealth::Ptr _health;
    Poco::OSP::ServiceRef::Ptr _healthRef;
};
} // namespace PocoDDS::ServiceClient

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(
        PocoDDS::ServiceClient::HttpInvocationProviderBundleActivator)
POCO_END_MANIFEST
