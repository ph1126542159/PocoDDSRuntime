#pragma once

#include "PocoDDS/Core/Bundle.h"
#include "PocoDDS/Core/BundleContext.h"

#include <memory>
#include <mutex>
#include <unordered_map>

namespace PocoDDS::Core
{
class BundleManager
{
  public:
    explicit BundleManager(ComponentRegistry& registry) : _context(registry) {}
    void install(std::unique_ptr<Bundle> bundle);
    void start(const std::string& name);
    void stop(const std::string& name);
    void uninstall(const std::string& name);

  private:
    struct Entry
    {
        std::unique_ptr<Bundle> bundle;
        bool running{false};
    };

    BundleContext _context;
    std::mutex _mutex;
    std::unordered_map<std::string, Entry> _bundles;
};
} // namespace PocoDDS::Core
