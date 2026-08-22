#include "PocoDDS/LocalIpc/Registration.h"

#include "PocoDDS/LocalIpc/LocalIpcTransport.h"

#include <chrono>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>

namespace PocoDDS::LocalIpc
{
using namespace PocoDDS::RuntimeCore;
namespace
{
Outcome<std::shared_ptr<IMessageTransport>>
createTransport(const TransportConfiguration& configuration)
{
    const auto endpoint = configuration.find("endpoint");
    if (endpoint == configuration.end() || endpoint->second.empty())
        return Outcome<std::shared_ptr<IMessageTransport>>::failure(
            {RuntimeErrorCode::invalidArgument,
             "local IPC transport requires a non-empty 'endpoint'", false});

    LocalIpcOptions options;
    options.endpoint = endpoint->second;
    if (const auto role = configuration.find("role"); role != configuration.end())
    {
        if (role->second == "server")
            options.role = EndpointRole::server;
        else if (role->second == "client")
            options.role = EndpointRole::client;
        else
            return Outcome<std::shared_ptr<IMessageTransport>>::failure(
                {RuntimeErrorCode::invalidArgument, "local IPC 'role' must be 'server' or 'client'",
                 false});
    }
    if (const auto token = configuration.find("authenticationToken"); token != configuration.end())
        options.authenticationToken = token->second;
    try
    {
        if (const auto maximum = configuration.find("maximumFrameBytes");
            maximum != configuration.end())
            options.maximumFrameBytes = static_cast<std::size_t>(std::stoull(maximum->second));
        if (const auto timeout = configuration.find("connectTimeoutMs");
            timeout != configuration.end())
            options.connectTimeout = std::chrono::milliseconds(std::stoll(timeout->second));
    }
    catch (const std::exception& exception)
    {
        return Outcome<std::shared_ptr<IMessageTransport>>::failure(
            {RuntimeErrorCode::invalidArgument,
             "invalid local IPC numeric configuration: " + std::string(exception.what()), false});
    }

    try
    {
        auto transport = std::make_shared<LocalIpcTransport>(std::move(options));
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

Outcome<TransportRegistration> registerLocalIpcTransport(ITransportRegistry& registry)
{
    return registry.registerFactory(
        {"ipc",
         "1.0.0",
         {false, true, false, false, false, false},
         {"endpoint", "role", "authenticationToken", "maximumFrameBytes", "connectTimeoutMs"}},
        createTransport);
}

} // namespace PocoDDS::LocalIpc
