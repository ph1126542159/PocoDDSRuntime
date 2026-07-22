#include "PocoDDS/Core/DynamicBundle.h"
#include "PocoDDS/Core/BundleLibrary.h"

#include <stdexcept>
#include <string>

#if defined(_WIN32)
#include <Windows.h>
#else
#include <dlfcn.h>
#endif

namespace PocoDDS::Core
{
namespace
{
#if defined(_WIN32)
using LibraryHandle = HMODULE;

LibraryHandle openLibrary(const std::filesystem::path& path) { return LoadLibraryW(path.c_str()); }

void closeLibrary(LibraryHandle handle) { FreeLibrary(handle); }

void* findSymbol(LibraryHandle handle, const char* name)
{
    return reinterpret_cast<void*>(GetProcAddress(handle, name));
}
#else
using LibraryHandle = void*;

LibraryHandle openLibrary(const std::filesystem::path& path)
{
    return dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
}

void closeLibrary(LibraryHandle handle) { dlclose(handle); }

void* findSymbol(LibraryHandle handle, const char* name) { return dlsym(handle, name); }
#endif

template <typename Function> Function requireSymbol(LibraryHandle handle, const char* name)
{
    auto symbol = findSymbol(handle, name);
    if (!symbol)
        throw std::runtime_error(std::string("bundle is missing symbol: ") + name);
    return reinterpret_cast<Function>(symbol);
}
} // namespace

class DynamicBundle::Impl
{
  public:
    explicit Impl(std::filesystem::path path) : libraryPath(std::move(path))
    {
        handle = openLibrary(libraryPath);
        if (!handle)
            throw std::runtime_error("cannot load bundle library: " + libraryPath.string());
        try
        {
            const auto abiVersion =
                requireSymbol<BundleAbiVersionFunction>(handle, "pdrBundleAbiVersion");
            if (abiVersion() != BundleAbiVersion)
                throw std::runtime_error("bundle ABI version mismatch");
            destroy = requireSymbol<DestroyBundleFunction>(handle, "pdrDestroyBundle");
            const auto create = requireSymbol<CreateBundleFunction>(handle, "pdrCreateBundle");
            bundle = create();
            if (!bundle)
                throw std::runtime_error("bundle factory returned null");
            bundleName = bundle->name();
            if (bundleName.empty())
                throw std::runtime_error("bundle name must not be empty");
        }
        catch (...)
        {
            if (bundle && destroy)
                destroy(bundle);
            closeLibrary(handle);
            throw;
        }
    }

    ~Impl()
    {
        if (bundle)
            destroy(bundle);
        if (handle)
            closeLibrary(handle);
    }

    std::filesystem::path libraryPath;
    LibraryHandle handle{};
    DestroyBundleFunction destroy{};
    Bundle* bundle{};
    std::string bundleName;
};

DynamicBundle::DynamicBundle(const std::filesystem::path& libraryPath)
    : _impl(std::make_unique<Impl>(libraryPath))
{
}

DynamicBundle::~DynamicBundle() = default;

std::string DynamicBundle::name() const { return _impl->bundleName; }

void DynamicBundle::start(BundleContext& context) { _impl->bundle->start(context); }

void DynamicBundle::stop(BundleContext& context) { _impl->bundle->stop(context); }

const std::filesystem::path& DynamicBundle::libraryPath() const { return _impl->libraryPath; }
} // namespace PocoDDS::Core
