#include "PocoDDS/TransportProviders/ProviderRegistration.h"

#include <exception>
#include <string>
#include <utility>

namespace PocoDDS::TransportProviders
{
namespace
{
RuntimeCore::RuntimeError invalidProvider(const std::string& message)
{
    return {RuntimeCore::RuntimeErrorCode::invalidArgument, message, false};
}
} // namespace

RuntimeCore::Outcome<RuntimeCore::TransportRegistration>
registerTransportProvider(RuntimeCore::ITransportRegistry& registry,
                          Poco::AutoPtr<TransportFactoryService> provider)
{
    if (!provider)
        return RuntimeCore::Outcome<RuntimeCore::TransportRegistration>::failure(
            invalidProvider("transport provider cannot be null"));

    RuntimeCore::TransportDescriptor descriptor;
    try
    {
        descriptor = provider->descriptor();
    }
    catch (const std::exception& exception)
    {
        return RuntimeCore::Outcome<RuntimeCore::TransportRegistration>::failure(
            invalidProvider("transport provider descriptor threw: " +
                            std::string(exception.what())));
    }
    catch (...)
    {
        return RuntimeCore::Outcome<RuntimeCore::TransportRegistration>::failure(
            invalidProvider("transport provider descriptor threw an unknown exception"));
    }

    return registry.registerFactory(
        std::move(descriptor),
        [provider = std::move(provider)](
            const RuntimeCore::TransportConfiguration& configuration)
        {
            return provider->create(configuration);
        });
}
} // namespace PocoDDS::TransportProviders
