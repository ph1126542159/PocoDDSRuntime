#include "PocoDDS/Core/BundleDirectoryWatcher.h"

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <system_error>

namespace PocoDDS::Core
{
BundleDirectoryWatcher::BundleDirectoryWatcher(BundleManager& manager,
                                               std::filesystem::path directory,
                                               std::chrono::milliseconds pollInterval)
    : _manager(manager), _directory(std::filesystem::absolute(std::move(directory))),
      _pollInterval(pollInterval)
{
    if (_pollInterval <= std::chrono::milliseconds::zero())
        throw std::invalid_argument("bundle poll interval must be positive");
    std::filesystem::create_directories(_directory);
}

BundleDirectoryWatcher::~BundleDirectoryWatcher() { stop(); }

std::vector<BundleFileEvent> BundleDirectoryWatcher::scan()
{
    std::unique_lock lock(_mutex);
    std::unordered_map<std::string, std::pair<std::filesystem::file_time_type, std::uintmax_t>>
        current;
    for (const auto& item : std::filesystem::directory_iterator(_directory))
    {
        if (!item.is_regular_file() || !isBundleLibrary(item.path()))
            continue;
        const auto path = std::filesystem::absolute(item.path()).lexically_normal().string();
        current.emplace(path, std::make_pair(item.last_write_time(), item.file_size()));
    }

    std::vector<BundleFileEvent> events;
    for (const auto& item : current)
    {
        const auto known = _known.find(item.first);
        if (known != _known.end() && known->second.lastWrite == item.second.first &&
            known->second.size == item.second.second)
            continue;
        try
        {
            const auto path = std::filesystem::path(item.first);
            if (known == _known.end() || known->second.bundleName.empty())
            {
                const auto name = _manager.upsertLibrary(path, true);
                _known[item.first] = {item.second.first, item.second.second, name};
                events.push_back({BundleFileEventKind::Installed, path, name, {}});
            }
            else
            {
                _manager.replaceLibrary(known->second.bundleName, path);
                known->second.lastWrite = item.second.first;
                known->second.size = item.second.second;
                events.push_back(
                    {BundleFileEventKind::Replaced, path, known->second.bundleName, {}});
            }
        }
        catch (const std::exception& error)
        {
            events.push_back({BundleFileEventKind::Failed, item.first, {}, error.what()});
        }
    }

    for (auto known = _known.begin(); known != _known.end();)
    {
        if (current.count(known->first) != 0)
        {
            ++known;
            continue;
        }
        try
        {
            if (!known->second.bundleName.empty())
                _manager.uninstall(known->second.bundleName);
            events.push_back(
                {BundleFileEventKind::Removed, known->first, known->second.bundleName, {}});
            known = _known.erase(known);
        }
        catch (const std::exception& error)
        {
            events.push_back({BundleFileEventKind::Failed, known->first, known->second.bundleName,
                              error.what()});
            ++known;
        }
    }
    const auto observers = _observers;
    lock.unlock();
    for (const auto& event : events)
        for (const auto& observer : observers)
            observer(event);
    return events;
}

void BundleDirectoryWatcher::observe(Observer observer)
{
    if (!observer)
        throw std::invalid_argument("bundle file observer must not be empty");
    std::lock_guard lock(_mutex);
    _observers.push_back(std::move(observer));
}

void BundleDirectoryWatcher::suppress(const std::string& bundleName)
{
    std::lock_guard lock(_mutex);
    for (auto& item : _known)
        if (item.second.bundleName == bundleName)
            item.second.bundleName.clear();
}

void BundleDirectoryWatcher::start()
{
    bool expected = false;
    if (!_running.compare_exchange_strong(expected, true))
        return;
    _thread = std::thread([this] { run(); });
}

void BundleDirectoryWatcher::stop()
{
    if (!_running.exchange(false))
        return;
    _changed.notify_all();
    if (_thread.joinable())
        _thread.join();
}

bool BundleDirectoryWatcher::isBundleLibrary(const std::filesystem::path& path) const
{
    const auto filename = path.filename().string();
    if (filename.rfind(".pdr-shadow-", 0) == 0)
        return false;
    auto extension = path.extension().string();
    std::transform(extension.begin(), extension.end(), extension.begin(),
                   [](unsigned char value) { return static_cast<char>(std::tolower(value)); });
#if defined(_WIN32)
    return extension == ".dll";
#elif defined(__APPLE__)
    return extension == ".dylib" || extension == ".so";
#else
    return extension == ".so";
#endif
}

void BundleDirectoryWatcher::run()
{
    while (_running)
    {
        try
        {
            scan();
        }
        catch (...)
        {
        }
        std::unique_lock lock(_mutex);
        _changed.wait_for(lock, _pollInterval, [&] { return !_running.load(); });
    }
}
} // namespace PocoDDS::Core
