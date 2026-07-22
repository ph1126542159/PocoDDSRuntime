#pragma once

#include "PocoDDS/Core/BundleManager.h"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace PocoDDS::Core
{
enum class BundleFileEventKind
{
    Installed,
    Replaced,
    Removed,
    Failed
};

struct BundleFileEvent
{
    BundleFileEventKind kind{BundleFileEventKind::Failed};
    std::filesystem::path path;
    std::string bundleName;
    std::string error;
};

class BundleDirectoryWatcher
{
  public:
    using Observer = std::function<void(const BundleFileEvent&)>;

    BundleDirectoryWatcher(BundleManager& manager, std::filesystem::path directory,
                           std::chrono::milliseconds pollInterval = std::chrono::seconds(1));
    ~BundleDirectoryWatcher();

    BundleDirectoryWatcher(const BundleDirectoryWatcher&) = delete;
    BundleDirectoryWatcher& operator=(const BundleDirectoryWatcher&) = delete;

    std::vector<BundleFileEvent> scan();
    void observe(Observer observer);
    void suppress(const std::string& bundleName);
    void start();
    void stop();

  private:
    struct FileState
    {
        std::filesystem::file_time_type lastWrite;
        std::uintmax_t size{0};
        std::string bundleName;
    };

    bool isBundleLibrary(const std::filesystem::path& path) const;
    void run();

    BundleManager& _manager;
    std::filesystem::path _directory;
    std::chrono::milliseconds _pollInterval;
    std::mutex _mutex;
    std::condition_variable _changed;
    std::unordered_map<std::string, FileState> _known;
    std::vector<Observer> _observers;
    std::atomic_bool _running{false};
    std::thread _thread;
};
} // namespace PocoDDS::Core
