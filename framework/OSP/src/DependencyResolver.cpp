#include "PocoDDS/OSP/DependencyResolver.h"

#include <functional>
#include <stdexcept>
#include <unordered_map>

namespace PocoDDS::OSP
{
std::vector<BundleManifest>
DependencyResolver::resolve(const std::vector<BundleManifest>& manifests) const
{
    enum class Mark
    {
        Visiting,
        Visited
    };
    std::unordered_map<std::string, const BundleManifest*> byName;
    for (const auto& manifest : manifests)
    {
        manifest.validate();
        if (!byName.emplace(manifest.symbolicName, &manifest).second)
            throw std::runtime_error("duplicate bundle: " + manifest.symbolicName);
    }

    std::unordered_map<std::string, Mark> marks;
    std::vector<BundleManifest> result;
    std::function<void(const BundleManifest&)> visit = [&](const BundleManifest& manifest)
    {
        const auto mark = marks.find(manifest.symbolicName);
        if (mark != marks.end())
        {
            if (mark->second == Mark::Visiting)
                throw std::runtime_error("cyclic bundle dependency: " + manifest.symbolicName);
            return;
        }
        marks.emplace(manifest.symbolicName, Mark::Visiting);
        for (const auto& requirement : manifest.requirements)
        {
            const auto dependency = byName.find(requirement.symbolicName);
            if (dependency == byName.end())
            {
                if (!requirement.optional)
                    throw std::runtime_error("missing bundle dependency: " +
                                             requirement.symbolicName);
                continue;
            }
            visit(*dependency->second);
        }
        marks[manifest.symbolicName] = Mark::Visited;
        result.push_back(manifest);
    };

    for (const auto& manifest : manifests)
        visit(manifest);
    return result;
}
} // namespace PocoDDS::OSP
