#include "PocoDDS/BundleManagement/BundleManager.h"

#include "Poco/DirectoryIterator.h"
#include "Poco/Event.h"
#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/Glob.h"
#include "Poco/Logger.h"
#include "Poco/OSP/BundleLoader.h"
#include "Poco/OSP/BundleRepository.h"
#include "Poco/OSP/OSPSubsystem.h"
#include "Poco/Path.h"
#include "Poco/StringTokenizer.h"
#include "Poco/Timestamp.h"

#include <algorithm>
#include <atomic>
#include <map>
#include <mutex>
#include <set>
#include <thread>
#include <utility>

namespace PocoDDS::BundleManagement
{
class BundleManager::Impl final
{
  public:
    using Snapshot =
        std::map<std::string, std::pair<Poco::Timestamp::TimeVal, Poco::File::FileSize>>;

    Impl(Poco::OSP::OSPSubsystem& osp, Poco::Logger& logger, BundleManagerOptions options)
        : _osp(osp), _logger(logger), _options(std::move(options))
    {
        _options.intervalMilliseconds = std::max<std::int64_t>(250, _options.intervalMilliseconds);
        _options.stableScanCount = std::max<std::size_t>(2, _options.stableScanCount);
    }

    ~Impl() { stop(); }

    void start()
    {
        bool expected = false;
        if (!_running.compare_exchange_strong(expected, true))
            return;

        _stop.reset();
        _worker = std::thread([this] { monitor(); });
        _logger.information("Bundle manager watching '%s' every %Ld ms.",
                            _options.repositories,
                            static_cast<long long>(_options.intervalMilliseconds));
    }

    void stop()
    {
        if (!_running.exchange(false))
            return;
        _stop.set();
        if (_worker.joinable())
            _worker.join();
    }

    void reload()
    {
        std::lock_guard<std::mutex> guard(_reloadMutex);
        _logger.information("Bundle repository changed; reloading bundles.");

        auto& loader = _osp.bundleLoader();
        loader.stopAllBundles();
        loader.unloadAllBundles();

        Poco::OSP::BundleRepository repository(_options.repositories, loader,
                                               _osp.getBundleFilter());
        repository.loadBundles();
        loader.resolveAllBundles();
        loader.startAllBundles();

        ++_successfulReloads;
        _logger.information("Bundle repository reload completed.");
    }

    bool running() const { return _running.load(); }
    std::size_t successfulReloads() const { return _successfulReloads.load(); }
    std::size_t failedReloads() const { return _failedReloads.load(); }

  private:
    void addPath(const std::string& path, Snapshot& snapshot) const
    {
        Poco::File file(path);
        if (!file.exists())
            return;

        Poco::Path normalized(path);
        normalized.makeAbsolute();
        snapshot[normalized.toString()] = {file.getLastModified().epochMicroseconds(),
                                           file.isFile() ? file.getSize() : 0};
        if (!file.isDirectory())
            return;

        for (Poco::DirectoryIterator iterator(path), end; iterator != end; ++iterator)
        {
            if (!iterator->isHidden())
                addPath(iterator->path(), snapshot);
        }
    }

    Snapshot scan() const
    {
#if defined(POCO_OS_FAMILY_UNIX)
        const std::string separators(":;");
#else
        const std::string separators(";");
#endif
        Poco::StringTokenizer paths(_options.repositories, separators,
                                    Poco::StringTokenizer::TOK_IGNORE_EMPTY |
                                        Poco::StringTokenizer::TOK_TRIM);
        Snapshot snapshot;
        for (const auto& path : paths)
        {
            Poco::File literal(path);
            if (literal.exists())
            {
                addPath(path, snapshot);
                continue;
            }

            std::set<std::string> matches;
#if defined(POCO_OS_FAMILY_WINDOWS)
            Poco::Glob::glob(path, matches, Poco::Glob::GLOB_CASELESS);
#else
            Poco::Glob::glob(path, matches, Poco::Glob::GLOB_DEFAULT);
#endif
            for (const auto& match : matches)
                addPath(match, snapshot);
        }
        return snapshot;
    }

    void monitor()
    {
        Snapshot applied = scan();
        Snapshot pending;
        std::size_t stableScans = 0;

        while (!_stop.tryWait(static_cast<long>(_options.intervalMilliseconds)))
        {
            try
            {
                Snapshot current = scan();
                if (current == applied)
                {
                    stableScans = 0;
                    pending.clear();
                    continue;
                }
                if (stableScans == 0 || current != pending)
                {
                    pending = std::move(current);
                    stableScans = 1;
                    continue;
                }
                ++stableScans;
                if (stableScans < _options.stableScanCount)
                    continue;

                reload();
                applied = std::move(current);
                pending.clear();
                stableScans = 0;
            }
            catch (const Poco::Exception& exception)
            {
                ++_failedReloads;
                _logger.error("Bundle repository reload failed: %s", exception.displayText());
            }
            catch (const std::exception& exception)
            {
                ++_failedReloads;
                _logger.error("Bundle repository reload failed: %s",
                              std::string(exception.what()));
            }
        }
    }

    Poco::OSP::OSPSubsystem& _osp;
    Poco::Logger& _logger;
    BundleManagerOptions _options;
    Poco::Event _stop;
    std::thread _worker;
    std::mutex _reloadMutex;
    std::atomic<bool> _running{false};
    std::atomic<std::size_t> _successfulReloads{0};
    std::atomic<std::size_t> _failedReloads{0};
};

BundleManager::BundleManager(Poco::OSP::OSPSubsystem& osp, Poco::Logger& logger,
                             BundleManagerOptions options)
    : _impl(new Impl(osp, logger, std::move(options)))
{
}

BundleManager::~BundleManager() { delete _impl; }
void BundleManager::start() { _impl->start(); }
void BundleManager::stop() { _impl->stop(); }
void BundleManager::reloadNow() { _impl->reload(); }
bool BundleManager::running() const { return _impl->running(); }
std::size_t BundleManager::successfulReloads() const { return _impl->successfulReloads(); }
std::size_t BundleManager::failedReloads() const { return _impl->failedReloads(); }
} // namespace PocoDDS::BundleManagement
