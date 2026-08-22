#include "PocoDDS/MqttTransport/Registration.h"

#include "PocoDDS/MqttTransport/MqttTransport.h"

#include <chrono>
#include <memory>
#include <stdexcept>
#include <string_view>

namespace PocoDDS::MqttTransport
{
using namespace PocoDDS::RuntimeCore;
namespace
{
bool parseBoolean(std::string_view key, const std::string& value)
{
    if (value == "true" || value == "1")
        return true;
    if (value == "false" || value == "0")
        return false;
    throw std::invalid_argument(std::string(key) + " must be true, false, 1, or 0");
}

Outcome<std::shared_ptr<IMessageTransport>>
createTransport(const TransportConfiguration& configuration)
{
    const auto server = configuration.find("serverUri");
    const auto client = configuration.find("clientId");
    if (server == configuration.end() || server->second.empty() || client == configuration.end() ||
        client->second.empty())
        return Outcome<std::shared_ptr<IMessageTransport>>::failure(
            {RuntimeErrorCode::invalidArgument,
             "MQTT transport requires non-empty 'serverUri' and 'clientId'", false});
    MqttTransportOptions options;
    options.serverUri = server->second;
    options.clientId = client->second;
    const auto assign = [&](const char* key, std::string& destination)
    {
        if (const auto found = configuration.find(key); found != configuration.end())
            destination = found->second;
    };
    assign("topicPrefix", options.topicPrefix);
    assign("username", options.username);
    assign("password", options.password);
    assign("trustStore", options.trustStore);
    assign("keyStore", options.keyStore);
    assign("privateKey", options.privateKey);
    assign("privateKeyPassword", options.privateKeyPassword);
    assign("enabledCipherSuites", options.enabledCipherSuites);
    try
    {
        const auto assignBoolean = [&](const char* key, bool& destination)
        {
            if (const auto found = configuration.find(key); found != configuration.end())
                destination = parseBoolean(key, found->second);
        };
        assignBoolean("verifyServerCertificate", options.verifyServerCertificate);
        assignBoolean("verifyHostname", options.verifyHostname);
        assignBoolean("cleanSession", options.cleanSession);
        if (const auto keepAlive = configuration.find("keepAliveSeconds");
            keepAlive != configuration.end())
            options.keepAliveSeconds = std::stoi(keepAlive->second);
        if (const auto timeout = configuration.find("connectTimeoutSeconds");
            timeout != configuration.end())
            options.connectTimeoutSeconds = std::stoi(timeout->second);
        if (const auto maximum = configuration.find("maximumFrameBytes");
            maximum != configuration.end())
            options.codecLimits.maximumFrameBytes =
                static_cast<std::size_t>(std::stoull(maximum->second));
    }
    catch (const std::exception& exception)
    {
        return Outcome<std::shared_ptr<IMessageTransport>>::failure(
            {RuntimeErrorCode::invalidArgument,
             "invalid MQTT numeric configuration: " + std::string(exception.what()), false});
    }
    try
    {
        auto transport = std::make_shared<MqttTransport>(std::move(options));
        const auto started = transport->start();
        if (!started)
            return Outcome<std::shared_ptr<IMessageTransport>>::failure(started.error());
        return Outcome<std::shared_ptr<IMessageTransport>>::success(std::move(transport));
    }
    catch (const std::exception& exception)
    {
        return Outcome<std::shared_ptr<IMessageTransport>>::failure(
            {RuntimeErrorCode::invalidArgument, exception.what(), false});
    }
}
} // namespace

Outcome<TransportRegistration> registerMqttTransport(ITransportRegistry& registry)
{
    return registry.registerFactory(
        {"mqtt",
         "1.0.0",
         {false, false, true, false, true, false},
         {"serverUri", "clientId", "topicPrefix", "username", "password", "trustStore", "keyStore",
          "privateKey", "privateKeyPassword", "enabledCipherSuites", "verifyServerCertificate",
          "verifyHostname", "cleanSession", "keepAliveSeconds", "connectTimeoutSeconds",
          "maximumFrameBytes"}},
        createTransport);
}

} // namespace PocoDDS::MqttTransport
