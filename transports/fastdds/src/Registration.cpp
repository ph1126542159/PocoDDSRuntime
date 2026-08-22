#include "PocoDDS/FastDdsTransport/Registration.h"

#include "PocoDDS/FastDdsTransport/FastDdsTransport.h"

#include <memory>
#include <stdexcept>

namespace PocoDDS::FastDdsTransport
{
using namespace PocoDDS::RuntimeCore;
namespace
{
Outcome<std::shared_ptr<IMessageTransport>>
createTransport(const TransportConfiguration& configuration)
{
    FastDdsTransportOptions options;
    if (const auto participant = configuration.find("participantName");
        participant != configuration.end())
        options.participantName = participant->second;
    if (const auto prefix = configuration.find("topicPrefix"); prefix != configuration.end())
        options.topicPrefix = prefix->second;
    try
    {
        if (const auto domain = configuration.find("domainId"); domain != configuration.end())
        {
            const auto value = std::stoull(domain->second);
            if (value > 232)
                throw std::out_of_range("domainId must be in range 0..232");
            options.domainId = static_cast<std::uint32_t>(value);
        }
        if (const auto maximum = configuration.find("maximumFrameBytes");
            maximum != configuration.end())
            options.codecLimits.maximumFrameBytes =
                static_cast<std::size_t>(std::stoull(maximum->second));
    }
    catch (const std::exception& exception)
    {
        return Outcome<std::shared_ptr<IMessageTransport>>::failure(
            {RuntimeErrorCode::invalidArgument,
             "invalid Fast DDS transport configuration: " + std::string(exception.what()), false});
    }
    try
    {
        auto transport = std::make_shared<FastDdsTransport>(std::move(options));
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

Outcome<TransportRegistration> registerFastDdsTransport(ITransportRegistry& registry)
{
    return registry.registerFactory(
        {"fastdds",
         "1.0.0",
         {false, false, true, false, false, false},
         {"domainId", "participantName", "topicPrefix", "maximumFrameBytes"}},
        createTransport);
}

} // namespace PocoDDS::FastDdsTransport
