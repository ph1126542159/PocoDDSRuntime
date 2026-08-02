#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace Poco::Util
{
class AbstractConfiguration;
}

namespace PocoDDS::Configuration
{
struct IndexedInstance
{
    std::size_t index{0};
    std::string prefix;
    std::string id;
    bool enabled{false};
    bool legacy{false};
};

/// Expands either the legacy single-instance keys (`base.enabled`, `base.*`)
/// or the indexed form (`base.count`, `base.0.*`, `base.1.*`). If count is
/// present it is authoritative and legacy keys are ignored.
[[nodiscard]] std::vector<IndexedInstance> indexedInstances(
    const Poco::Util::AbstractConfiguration& configuration,
    const std::string& base,
    bool legacyEnabledDefault,
    std::size_t indexedDefaultCount,
    const std::string& defaultIdPrefix,
    std::size_t maximumCount = 256);
}
