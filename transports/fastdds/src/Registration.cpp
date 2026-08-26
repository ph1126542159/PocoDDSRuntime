#include "PocoDDS/FastDdsTransport/Registration.h"

#include "PocoDDS/FastDdsTransport/FastDdsTransport.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <utility>
#include <vector>

namespace PocoDDS::FastDdsTransport
{
using namespace PocoDDS::RuntimeCore;
namespace
{
constexpr std::array<std::string_view, 4> configurationKeys{
    "domainId", "participantName", "topicPrefix", "maximumFrameBytes"};

std::uint64_t parseUnsigned(const std::string& value, const char* key,
                            std::uint64_t minimum, std::uint64_t maximum)
{
    std::uint64_t parsed = 0;
    const auto* begin = value.data();
    const auto* end = begin + value.size();
    const auto conversion = std::from_chars(begin, end, parsed);
    if (conversion.ec != std::errc{} || conversion.ptr != end || parsed < minimum ||
        parsed > maximum)
        throw std::invalid_argument(std::string(key) + " must be in range " +
                                    std::to_string(minimum) + ".." +
                                    std::to_string(maximum));
    return parsed;
}

void rejectUnknownKeys(const TransportConfiguration& configuration)
{
    for (const auto& [key, _] : configuration)
    {
        if (std::find(configurationKeys.begin(), configurationKeys.end(), key) ==
            configurationKeys.end())
            throw std::invalid_argument("unknown Fast DDS transport configuration key: " + key);
    }
}
} // namespace

TransportDescriptor fastDdsTransportDescriptor()
{
    std::vector<std::string> keys;
    keys.reserve(configurationKeys.size());
    for (const auto key : configurationKeys)
        keys.emplace_back(key);
    return {"fastdds",
            "1.0.0",
            {false, false, true, false, false, false},
            std::move(keys)};
}

Outcome<std::shared_ptr<IMessageTransport>>
createFastDdsTransport(const TransportConfiguration& configuration)
{
    FastDdsTransportOptions options;
    try
    {
        rejectUnknownKeys(configuration);
        if (const auto participant = configuration.find("participantName");
            participant != configuration.end())
            options.participantName = participant->second;
        if (const auto prefix = configuration.find("topicPrefix"); prefix != configuration.end())
            options.topicPrefix = prefix->second;
        if (const auto domain = configuration.find("domainId"); domain != configuration.end())
            options.domainId = static_cast<std::uint32_t>(
                parseUnsigned(domain->second, "domainId", 0, 232));
        if (const auto maximum = configuration.find("maximumFrameBytes");
            maximum != configuration.end())
            options.codecLimits.maximumFrameBytes =
                static_cast<std::size_t>(parseUnsigned(
                    maximum->second, "maximumFrameBytes", 1, 180U * 1024U));
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

Outcome<TransportRegistration> registerFastDdsTransport(ITransportRegistry& registry)
{
    return registry.registerFactory(fastDdsTransportDescriptor(), createFastDdsTransport);
}

} // namespace PocoDDS::FastDdsTransport
