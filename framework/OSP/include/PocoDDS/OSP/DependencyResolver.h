#pragma once

#include "PocoDDS/OSP/BundleManifest.h"

#include <vector>

namespace PocoDDS::OSP
{
class DependencyResolver
{
  public:
    std::vector<BundleManifest> resolve(const std::vector<BundleManifest>& manifests) const;
};
} // namespace PocoDDS::OSP
