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
    const auto name = bundle->name();
    if (_bundles.count(name) != 0)
        throw std::runtime_error("bundle already installed");
    _bundles.emplace(name, Entry{std::move(bundle), false});
    publish(name, ComponentState::Stopped);
}

std::string BundleManager::installLibrary(const std::filesystem::path& libraryPath)
{
    auto bundle = std::make_unique<DynamicBundle>(libraryPath);
    const auto name = bundle->name();
    install(std::move(bundle));
    return name;
}

std::string BundleManager::upsertLibrary(const std::filesystem::path& libraryPath,
                                         bool startAfterInstall)
{
    auto replacement = std::make_unique<DynamicBundle>(libraryPath);
    const auto name = replacement->name();
    std::lock_guard lock(_mutex);
    const auto found = _bundles.find(name);
    if (found == _bundles.end())
    {
        auto [inserted, created] = _bundles.emplace(name, Entry{std::move(replacement), false});
        static_cast<void>(created);
        publish(name, ComponentState::Stopped);
        if (startAfterInstall)
        {
            publish(name, ComponentState::Starting);
            try
            {
                inserted->second.bundle->start(_context);
                inserted->second.running = true;
                publish(name, ComponentState::Running);
            }
            catch (...)
            {
                _bundles.erase(inserted);
                publish(name, ComponentState::Failed);
                throw;
            }
        }
        return name;
    }

    auto& entry = found->second;
    const bool shouldRun = entry.running || startAfterInstall;
    if (entry.running)
    {
        publish(name, ComponentState::Stopping);
        entry.bundle->stop(_context);
    }
    auto previous = std::move(entry.bundle);
    entry.bundle = std::move(replacement);
    entry.running = false;
    if (shouldRun)
    {
        publish(name, ComponentState::Starting);
        try
        {
            entry.bundle->start(_context);
            entry.running = true;
            publish(name, ComponentState::Running);
        }
        catch (...)
        {
            entry.bundle = std::move(previous);
            entry.bundle->start(_context);
            entry.running = true;
            publish(name, ComponentState::Running);
            throw;
        }
    }
    else
        publish(name, ComponentState::Stopped);
    return name;
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
    {
        publish(name, ComponentState::Stopping);
        entry.bundle->stop(_context);
    }
    auto previous = std::move(entry.bundle);
    entry.bundle = std::move(replacement);
    entry.running = false;
    if (!wasRunning)
    {
        publish(name, ComponentState::Stopped);
        return;
    }
    publish(name, ComponentState::Starting);
    try
    {
        entry.bundle->start(_context);
        entry.running = true;
        publish(name, ComponentState::Running);
    }
    catch (...)
    {
        entry.bundle = std::move(previous);
        entry.bundle->start(_context);
        entry.running = true;
        publish(name, ComponentState::Running);
        throw;
    }
}

void BundleManager::start(const std::string& name)
{
    std::lock_guard lock(_mutex);
    auto& entry = _bundles.at(name);
    if (entry.running)
        return;
    publish(name, ComponentState::Starting);
    try
    {
        entry.bundle->start(_context);
        entry.running = true;
        publish(name, ComponentState::Running);
    }
    catch (...)
    {
        publish(name, ComponentState::Failed);
        throw;
    }
}

void BundleManager::stop(const std::string& name)
{
    std::lock_guard lock(_mutex);
    auto& entry = _bundles.at(name);
    if (!entry.running)
        return;
    publish(name, ComponentState::Stopping);
    try
    {
        entry.bundle->stop(_context);
        entry.running = false;
        publish(name, ComponentState::Stopped);
    }
    catch (...)
    {
        publish(name, ComponentState::Failed);
        throw;
    }
}

void BundleManager::uninstall(const std::string& name)
{
    stop(name);
    std::lock_guard lock(_mutex);
    _bundles.erase(name);
    _context.registry().remove(name);
}

void BundleManager::publish(const std::string& name, ComponentState state)
{
    _context.registry().upsert({name, name, "localhost", 0, ComponentKind::Bundle, state, {}});
}
} // namespace PocoDDS::Core
