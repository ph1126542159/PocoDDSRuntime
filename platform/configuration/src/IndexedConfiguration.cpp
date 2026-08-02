#include "PocoDDS/Configuration/IndexedConfiguration.h"

#include "Poco/Exception.h"
#include "Poco/Util/AbstractConfiguration.h"

#include <unordered_set>
#include <utility>

namespace PocoDDS::Configuration
{
std::vector<IndexedInstance> indexedInstances(
    const Poco::Util::AbstractConfiguration& configuration,
    const std::string& base,
    bool legacyEnabledDefault,
    std::size_t indexedDefaultCount,
    const std::string& defaultIdPrefix,
    std::size_t maximumCount)
{
    const std::string countKey = base + ".count";
    const bool indexed = configuration.hasProperty(countKey);
    const auto count = indexed
        ? static_cast<std::size_t>(configuration.getUInt(countKey))
        : indexedDefaultCount;
    if (count > maximumCount)
        throw Poco::InvalidArgumentException(countKey + " exceeds maximum " +
                                             std::to_string(maximumCount));

    std::vector<IndexedInstance> result;
    if (!indexed)
    {
        const bool enabled = configuration.getBool(base + ".enabled", legacyEnabledDefault);
        if (enabled || indexedDefaultCount > 0)
            result.push_back({0, base,
                              configuration.getString(base + ".id", defaultIdPrefix + "-1"),
                              enabled, true});
        return result;
    }

    std::unordered_set<std::string> ids;
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index)
    {
        const std::string prefix = base + "." + std::to_string(index);
        IndexedInstance instance{
            index,
            prefix,
            configuration.getString(prefix + ".id",
                                    defaultIdPrefix + "-" + std::to_string(index + 1)),
            configuration.getBool(prefix + ".enabled", true),
            false};
        if (instance.enabled && instance.id.empty())
            throw Poco::InvalidArgumentException(prefix + ".id must not be empty");
        if (instance.enabled && !ids.insert(instance.id).second)
            throw Poco::InvalidArgumentException(base + " contains duplicate id " + instance.id);
        result.push_back(std::move(instance));
    }
    return result;
}
}
