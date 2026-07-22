#include "PocoDDS/Core/BundleManager.h"

#include <stdexcept>

namespace PocoDDS::Core
{
void BundleManager::install(std::unique_ptr<Bundle> bundle)
{
    if (!bundle)
        throw std::invalid_argument("bundle must not be null");
    std::lock_guard lock(_mutex);
    const auto bundleName = bundle->name();
    if (_bundles.count(bundleName) != 0)
        throw std::runtime_error("bundle already installed");
    _bundles.emplace(bundleName, Entry{std::move(bundle), false});
}

void BundleManager::start(const std::string& name)
{
    std::lock_guard lock(_mutex);
    auto& entry = _bundles.at(name);
    if (!entry.running)
    {
        entry.bundle->start(_context);
        entry.running = true;
    }
}

void BundleManager::stop(const std::string& name)
{
    std::lock_guard lock(_mutex);
    auto& entry = _bundles.at(name);
    if (entry.running)
    {
        entry.bundle->stop(_context);
        entry.running = false;
    }
}

void BundleManager::uninstall(const std::string& name)
{
    stop(name);
    std::lock_guard lock(_mutex);
    _bundles.erase(name);
}
} // namespace PocoDDS::Core
