#pragma once

#include <string>
#include <vector>

namespace PocoDDS::OSP
{
struct BundleRequirement
{
    std::string symbolicName;
    std::string minimumVersion;
    bool optional{false};
};

struct BundleManifest
{
    std::string symbolicName;
    std::string version;
    std::string activator;
    std::vector<BundleRequirement> requirements;

    void validate() const;
};
} // namespace PocoDDS::OSP
