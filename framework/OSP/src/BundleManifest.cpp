#include "PocoDDS/OSP/BundleManifest.h"

#include <stdexcept>

namespace PocoDDS::OSP
{
void BundleManifest::validate() const
{
    if (symbolicName.empty())
        throw std::invalid_argument("bundle symbolic name must not be empty");
    if (version.empty())
        throw std::invalid_argument("bundle version must not be empty");
    for (const auto& requirement : requirements)
    {
        if (requirement.symbolicName.empty())
            throw std::invalid_argument("bundle requirement name must not be empty");
    }
}
} // namespace PocoDDS::OSP
