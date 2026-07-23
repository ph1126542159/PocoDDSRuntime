#include "PocoDDS/ProcessManagement/SubprocessManager.h"

#include "Poco/AutoPtr.h"
#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/Logger.h"
#include "Poco/Mutex.h"
#include "Poco/Path.h"
#include "Poco/Process.h"
#include "Poco/Thread.h"
#include "Poco/Timestamp.h"
#include "Poco/Util/PropertyFileConfiguration.h"

#include <algorithm>
#include <cctype>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>

namespace PocoDDS::ProcessManagement
{
namespace
{
SubprocessManager* activeManager = nullptr;

std::string resolveRelativePath(const std::string& rootDirectory, const std::string& relativePath)
{
    Poco::Path configured(relativePath);
    if (configured.isAbsolute())
        throw Poco::InvalidArgumentException("Subprocess path must be relative", relativePath);

    Poco::Path root(rootDirectory);
    root.makeAbsolute();
    root.makeDirectory();
    Poco::Path resolved(root);
    resolved.resolve(configured);
    resolved.makeAbsolute();

    std::string rootText = root.toString();
    std::string resolvedText = resolved.toString();
#if defined(POCO_OS_FAMILY_WINDOWS)
    const auto lower = [](unsigned char character) {
        return static_cast<char>(std::tolower(character));
    };
    std::transform(rootText.begin(), rootText.end(), rootText.begin(), lower);
    std::transform(resolvedText.begin(), resolvedText.end(), resolvedText.begin(), lower);
#endif
    if (resolvedText.rfind(rootText, 0) != 0)
        throw Poco::InvalidArgumentException("Subprocess path escapes process root", relativePath);
    return resolved.toString();
}
} // namespace

class SubprocessManager::Impl final
{
  public:
    struct ConfiguredProcess
    {
        std::string name;
        std::string executable;
        Poco::Process::Args arguments;
        std::string initialDirectory;
        std::string location{"local"};
    };

    struct RunningProcess
    {
        std::string name;
        std::unique_ptr<Poco::ProcessHandle> handle;
    };

    Impl(Poco::Logger& logger, SubprocessManagerOptions options)
        : _logger(logger), _options(options)
    {
        _options.shutdownTimeoutMilliseconds =
            std::max<std::int64_t>(0, _options.shutdownTimeoutMilliseconds);
    }

    ~Impl() { stopAll(); }

    std::size_t start(const std::string& configurationPath, const std::string& rootDirectory)
    {
        stopAll();
        Poco::FastMutex::ScopedLock lock(_mutex);
        _configured.clear();
        Poco::File configurationFile(configurationPath);
        if (!configurationFile.exists())
        {
            _logger.warning("Subprocess configuration not found: %s", configurationPath);
            return 0;
        }

        Poco::AutoPtr<Poco::Util::PropertyFileConfiguration> configuration =
            new Poco::Util::PropertyFileConfiguration(configurationPath);
        const int count = std::max(0, configuration->getInt("subprocess.count", 0));

        try
        {
            for (int index = 0; index < count; ++index)
            {
                const std::string prefix = "subprocess." + std::to_string(index) + ".";
                if (!configuration->getBool(prefix + "enabled", true))
                    continue;

                const std::string relativePath = configuration->getString(prefix + "path");
                const std::string executable =
                    resolveRelativePath(rootDirectory, relativePath);
                Poco::File executableFile(executable);
                if (!executableFile.exists() || !executableFile.isFile())
                    throw Poco::FileNotFoundException("Subprocess executable", executable);

                Poco::Process::Args arguments;
                const int argumentCount =
                    std::max(0, configuration->getInt(prefix + "argument.count", 0));
                for (int argument = 0; argument < argumentCount; ++argument)
                {
                    arguments.push_back(configuration->getString(
                        prefix + "argument." + std::to_string(argument)));
                }

                std::string initialDirectory;
                if (configuration->hasProperty(prefix + "workingDirectory"))
                {
                    initialDirectory = resolveRelativePath(
                        rootDirectory, configuration->getString(prefix + "workingDirectory"));
                }
                else
                {
                    Poco::Path parent(executable);
                    parent.makeParent();
                    initialDirectory = parent.toString();
                }

                const std::string name =
                    configuration->getString(prefix + "name", Poco::Path(executable).getBaseName());
                std::string location = configuration->getString(prefix + "location", "local");
                std::transform(location.begin(), location.end(), location.begin(),
                               [](unsigned char value) {
                                   return static_cast<char>(std::tolower(value));
                               });
                if (location != "local" && location != "remote")
                    throw Poco::InvalidArgumentException(
                        "Subprocess location must be local or remote", location);
                _configured.push_back(
                    {name, executable, arguments, initialDirectory, location});
                if (location == "local")
                    launch(_configured.back());
                else
                    _logger.information("Registered remote subprocess '%s'; local launch skipped.",
                                        name);
            }
        }
        catch (...)
        {
            for (auto iterator = _running.rbegin(); iterator != _running.rend(); ++iterator)
                stopProcess(*iterator);
            _running.clear();
            throw;
        }
        return _running.size();
    }

    void stopAll()
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        for (auto iterator = _running.rbegin(); iterator != _running.rend(); ++iterator)
            stopProcess(*iterator);
        _running.clear();
    }

    bool startOne(const std::string& name)
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        const auto configured = findConfigured(name);
        if (configured == _configured.end() || configured->location != "local")
            return false;
        const auto running = findRunning(name);
        if (running != _running.end() && Poco::Process::isRunning(*running->handle))
            return true;
        if (running != _running.end())
            _running.erase(running);
        launch(*configured);
        return true;
    }

    bool stopOne(const std::string& name)
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        const auto running = findRunning(name);
        if (running == _running.end())
            return findConfigured(name) != _configured.end();
        stopProcess(*running);
        _running.erase(running);
        return true;
    }

    bool restartOne(const std::string& name)
    {
        if (!stopOne(name))
            return false;
        return startOne(name);
    }

    std::vector<SubprocessInfo> processes() const
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        std::vector<SubprocessInfo> result;
        result.reserve(_configured.size());
        for (const auto& configured : _configured)
        {
            SubprocessInfo info;
            info.name = configured.name;
            info.location = configured.location;
            info.manageable = configured.location == "local";
            const auto running = findRunning(configured.name);
            if (running != _running.end() && Poco::Process::isRunning(*running->handle))
            {
                info.state = "running";
                info.processId = static_cast<unsigned long>(running->handle->id());
            }
            result.push_back(std::move(info));
        }
        return result;
    }

    std::size_t runningCount() const
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        return static_cast<std::size_t>(
            std::count_if(_running.begin(), _running.end(), [](const RunningProcess& process) {
                return Poco::Process::isRunning(*process.handle);
            }));
    }

  private:
    void launch(const ConfiguredProcess& process)
    {
        _logger.information("Starting local subprocess '%s': %s", process.name,
                            process.executable);
        auto handle = std::make_unique<Poco::ProcessHandle>(
            Poco::Process::launch(process.executable, process.arguments,
                                  process.initialDirectory));
        _logger.information("Subprocess '%s' started with PID %d.", process.name,
                            static_cast<int>(handle->id()));
        _running.push_back({process.name, std::move(handle)});
    }

    void stopProcess(RunningProcess& process)
    {
        if (!Poco::Process::isRunning(*process.handle))
            return;
        _logger.information("Stopping subprocess '%s' (PID %d).", process.name,
                            static_cast<int>(process.handle->id()));
        Poco::Process::requestTermination(process.handle->id());
        const Poco::Timestamp::TimeVal timeoutMicroseconds =
            _options.shutdownTimeoutMilliseconds * 1000;
        Poco::Timestamp started;
        while (Poco::Process::isRunning(*process.handle) &&
               !started.isElapsed(timeoutMicroseconds))
            Poco::Thread::sleep(50);
        if (Poco::Process::isRunning(*process.handle))
        {
            _logger.warning("Subprocess '%s' did not stop in time; terminating it.",
                            process.name);
            Poco::Process::kill(*process.handle);
        }
    }

    auto findConfigured(const std::string& name)
    {
        return std::find_if(_configured.begin(), _configured.end(),
                            [&](const ConfiguredProcess& process) {
                                return process.name == name;
                            });
    }

    auto findConfigured(const std::string& name) const
    {
        return std::find_if(_configured.begin(), _configured.end(),
                            [&](const ConfiguredProcess& process) {
                                return process.name == name;
                            });
    }

    auto findRunning(const std::string& name)
    {
        return std::find_if(_running.begin(), _running.end(),
                            [&](const RunningProcess& process) {
                                return process.name == name;
                            });
    }

    auto findRunning(const std::string& name) const
    {
        return std::find_if(_running.begin(), _running.end(),
                            [&](const RunningProcess& process) {
                                return process.name == name;
                            });
    }

    Poco::Logger& _logger;
    SubprocessManagerOptions _options;
    std::vector<ConfiguredProcess> _configured;
    std::vector<RunningProcess> _running;
    mutable Poco::FastMutex _mutex;
};

SubprocessManager::SubprocessManager(Poco::Logger& logger, SubprocessManagerOptions options)
    : _impl(new Impl(logger, options))
{
    activeManager = this;
}

SubprocessManager::~SubprocessManager()
{
    if (activeManager == this)
        activeManager = nullptr;
    delete _impl;
}

std::size_t SubprocessManager::startFromConfiguration(const std::string& configurationPath,
                                                      const std::string& processRootDirectory)
{
    return _impl->start(configurationPath, processRootDirectory);
}

void SubprocessManager::stopAll() { _impl->stopAll(); }
bool SubprocessManager::start(const std::string& name) { return _impl->startOne(name); }
bool SubprocessManager::stop(const std::string& name) { return _impl->stopOne(name); }
bool SubprocessManager::restart(const std::string& name) { return _impl->restartOne(name); }
std::vector<SubprocessInfo> SubprocessManager::processes() const { return _impl->processes(); }
std::size_t SubprocessManager::runningCount() const { return _impl->runningCount(); }
SubprocessManager* SubprocessManager::active() noexcept { return activeManager; }
} // namespace PocoDDS::ProcessManagement
