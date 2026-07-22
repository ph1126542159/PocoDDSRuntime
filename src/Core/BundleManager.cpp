#include "PocoDDS/Core/BundleManager.h"
#include "PocoDDS/Core/DynamicBundle.h"

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

std::string BundleManager::installLibrary(const std::filesystem::path& libraryPath)
{
    auto bundle = std::make_unique<DynamicBundle>(libraryPath);
    const auto bundleName = bundle->name();
    install(std::move(bundle));
    return bundleName;
}

void BundleManager::replaceLibrary(const std::string& name,
                                   const std::filesystem::path& libraryPath)
{
    auto replacement = std::make_unique<DynamicBundle>(libraryPath);
    if (replacement->name() != name)
        throw std::runtime_error("replacement bundle name mismatch");

    std::lock_guard lock(_mutex);
    auto& entry = _bundles.at(name);
    const bool wasRunning = entry.running;
    if (wasRunning)
        entry.bundle->stop(_context);
    auto previous = std::move(entry.bundle);
    entry.bundle = std::move(replacement);
    entry.running = false;
    if (wasRunning)
    {
        try
        {
            entry.bundle->start(_context);
            entry.running = true;
        }
        catch (...)
        {
            entry.bundle = std::move(previous);
            entry.bundle->start(_context);
            entry.running = true;
            throw;
        }
    }
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
