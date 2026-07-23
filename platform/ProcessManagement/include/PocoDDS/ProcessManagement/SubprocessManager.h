#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#if defined(_WIN32)
#if defined(PDR_PROCESS_MANAGEMENT_EXPORTS)
#define PDR_PROCESS_MANAGEMENT_API __declspec(dllexport)
#else
#define PDR_PROCESS_MANAGEMENT_API __declspec(dllimport)
#endif
#else
#define PDR_PROCESS_MANAGEMENT_API
#endif

namespace Poco
{
class Logger;
}

namespace PocoDDS::ProcessManagement
{
struct SubprocessManagerOptions
{
    std::int64_t shutdownTimeoutMilliseconds{5000};
};

class PDR_PROCESS_MANAGEMENT_API SubprocessManager final
{
  public:
    explicit SubprocessManager(Poco::Logger& logger,
                               SubprocessManagerOptions options = {});
    ~SubprocessManager();

    SubprocessManager(const SubprocessManager&) = delete;
    SubprocessManager& operator=(const SubprocessManager&) = delete;

    std::size_t startFromConfiguration(const std::string& configurationPath,
                                       const std::string& processRootDirectory);
    void stopAll();

    std::size_t runningCount() const;

  private:
    class Impl;
    Impl* _impl;
};
} // namespace PocoDDS::ProcessManagement
