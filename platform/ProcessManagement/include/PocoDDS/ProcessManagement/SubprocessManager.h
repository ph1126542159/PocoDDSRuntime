#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

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

struct SubprocessInfo
{
    std::string name;
    std::string location{"local"};
    std::string state{"stopped"};
    unsigned long processId{0};
    bool manageable{true};
    bool required{true};
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
    bool start(const std::string& name);
    bool stop(const std::string& name);
    bool restart(const std::string& name);
    std::vector<SubprocessInfo> processes() const;

    std::size_t runningCount() const;

    static SubprocessManager* active() noexcept;

  private:
    class Impl;
    Impl* _impl;
};
} // namespace PocoDDS::ProcessManagement
