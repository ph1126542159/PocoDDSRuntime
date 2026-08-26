#pragma once

#include "PocoDDS/BundleManagement/BundleRepositoryAuthorization.h"

#include <cstddef>
#include <cstdint>
#include <string>

#if defined(_WIN32)
#if defined(PDR_BUNDLE_MANAGEMENT_EXPORTS)
#define PDR_BUNDLE_MANAGEMENT_API __declspec(dllexport)
#else
#define PDR_BUNDLE_MANAGEMENT_API __declspec(dllimport)
#endif
#else
#define PDR_BUNDLE_MANAGEMENT_API
#endif

namespace Poco
{
class Logger;
namespace OSP
{
class OSPSubsystem;
}
} // namespace Poco

namespace PocoDDS::BundleManagement
{
struct BundleManagerOptions
{
    std::string repositories;
    std::string stateDirectory;
    std::int64_t intervalMilliseconds{1000};
    std::size_t stableScanCount{2};
    bool inProcessReloadEnabled{false};
    BundleRepositoryAuthorizationOptions authorization;
};

class PDR_BUNDLE_MANAGEMENT_API BundleManager final
{
  public:
    BundleManager(Poco::OSP::OSPSubsystem& osp, Poco::Logger& logger,
                  BundleManagerOptions options);
    ~BundleManager();

    BundleManager(const BundleManager&) = delete;
    BundleManager& operator=(const BundleManager&) = delete;

    void start();
    void stop();
    void reloadNow();

    bool running() const;
    std::size_t successfulReloads() const;
    std::size_t failedReloads() const;
    std::size_t rejectedReloads() const;
    std::size_t rolledBackReloads() const;
    std::size_t restartRequiredReloads() const;
    std::string lastError() const;

  private:
    class Impl;
    Impl* _impl;
};
} // namespace PocoDDS::BundleManagement
