#include "PocoDDS/Robotics/BusinessPlugin.h"

#include <filesystem>
#include <stdexcept>
#include <utility>

#if defined(_WIN32)
#include <Windows.h>
#else
#include <dlfcn.h>
#endif

namespace PocoDDS::Robotics
{
namespace
{
class DynamicLibrary
{
  public:
    explicit DynamicLibrary(const std::string& path)
    {
        if (path.empty())
            throw std::invalid_argument("business plugin path is required");
#if defined(_WIN32)
        _handle = LoadLibraryW(std::filesystem::u8path(path).c_str());
        if (!_handle)
            throw std::runtime_error("business plugin could not be loaded: " + path +
                                     ", error=" + std::to_string(GetLastError()));
#else
        _handle = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
        if (!_handle)
            throw std::runtime_error("business plugin could not be loaded: " + path + ": " +
                                     std::string(dlerror()));
#endif
    }

    ~DynamicLibrary()
    {
        if (!_handle)
            return;
#if defined(_WIN32)
        FreeLibrary(_handle);
#else
        dlclose(_handle);
#endif
    }

    DynamicLibrary(const DynamicLibrary&) = delete;
    DynamicLibrary& operator=(const DynamicLibrary&) = delete;

    BusinessPluginEntry entry() const
    {
#if defined(_WIN32)
        const auto symbol = GetProcAddress(_handle, businessPluginEntryPoint);
#else
        dlerror();
        const auto symbol = dlsym(_handle, businessPluginEntryPoint);
#endif
        if (!symbol)
            throw std::runtime_error("business plugin entry point is missing");
        return reinterpret_cast<BusinessPluginEntry>(symbol);
    }

  private:
#if defined(_WIN32)
    HMODULE _handle{nullptr};
#else
    void* _handle{nullptr};
#endif
};
} // namespace

std::shared_ptr<RobotBusinessModule> BusinessPluginLoader::load(const std::string& path)
{
    auto library = std::make_shared<DynamicLibrary>(path);
    const auto descriptor = library->entry()();
    if (!descriptor || descriptor->structureSize < sizeof(BusinessPluginDescriptor) ||
        descriptor->abiVersion != businessPluginAbiVersion || !descriptor->name ||
        std::string(descriptor->name).empty() || !descriptor->create || !descriptor->destroy)
        throw std::runtime_error("business plugin descriptor is invalid: " + path);
    auto* instance = descriptor->create();
    if (!instance)
        throw std::runtime_error("business plugin factory returned null: " + path);
    std::shared_ptr<RobotBusinessModule> module(
        instance,
        [library, destroy = descriptor->destroy](RobotBusinessModule* value) noexcept
        {
            destroy(value);
            static_cast<void>(library);
        });
    if (module->name() != descriptor->name)
        throw std::runtime_error("business plugin name does not match its module: " + path);
    return module;
}
} // namespace PocoDDS::Robotics
