#include "PocoDDS/ProcessManagement/SubprocessManager.h"
#include "PocoDDS/ProcessManagement/ProcessDependencyGraph.h"
#include "PocoDDS/ProcessManagement/ProcessDesiredStateMaintenance.h"

#include "ProcessDesiredStateStore.h"
#include "ProcessDependencyGraphRegistry.h"

#include "Poco/AutoPtr.h"
#include "Poco/Exception.h"
#include "Poco/Event.h"
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
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

namespace PocoDDS::ProcessManagement
{
namespace
{
SubprocessManager* activeManager = nullptr;

struct FileSignal
{
    bool available{false};
    Poco::File::FileSize size{0};
    Poco::Timestamp modified;
    std::string sample;
};

FileSignal fileSignal(const std::string& path)
{
    try
    {
        Poco::File file(path);
        if (!file.exists() || !file.isFile() || file.getSize() == 0)
            return {};
        FileSignal signal;
        signal.available = true;
        signal.size = file.getSize();
        signal.modified = file.getLastModified();
        std::ifstream input(path, std::ios::binary);
        if (!input)
            return {};
        signal.sample.resize(4096);
        input.read(signal.sample.data(),
                   static_cast<std::streamsize>(signal.sample.size()));
        signal.sample.resize(static_cast<std::size_t>(input.gcount()));
        if (signal.sample.empty())
            return {};
        return signal;
    }
    catch (...)
    {
        // Writers may replace or truncate the file between metadata and data
        // reads. Treat that scan as unavailable and retry on the next tick.
        return {};
    }
}

bool sameSignal(const FileSignal& left, const FileSignal& right)
{
    return left.available == right.available && left.size == right.size &&
        left.modified == right.modified && left.sample == right.sample;
}

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
    const auto lower = [](unsigned char character)
    { return static_cast<char>(std::tolower(character)); };
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
        bool required{true};
        std::string restartPolicy{"never"};
        std::uint64_t maximumRestartAttempts{0};
        std::int64_t initialBackoffMilliseconds{250};
        std::int64_t maximumBackoffMilliseconds{30000};
        double backoffMultiplier{2.0};
        std::int64_t resetAfterMilliseconds{60000};
        bool desiredRunning{false};
        std::uint64_t consecutiveRestartAttempts{0};
        std::string recoveryState{"stopped"};
        std::int64_t nextBackoffMilliseconds{250};
        std::chrono::steady_clock::time_point nextRestart;
        std::string readinessFile;
        std::int64_t readinessTimeoutMilliseconds{0};
        std::int64_t heartbeatTimeoutMilliseconds{0};
        std::vector<std::string> dependencies;
        bool restartPending{false};
    };

    struct RunningProcess
    {
        std::string name;
        std::unique_ptr<Poco::ProcessHandle> handle;
        std::chrono::steady_clock::time_point started;
        bool ready{true};
        std::chrono::steady_clock::time_point readyAt;
        std::chrono::steady_clock::time_point lastSignalObserved;
        FileSignal signal;
    };

    Impl(Poco::Logger& logger, SubprocessManagerOptions options)
        : _logger(logger), _options(options)
    {
        _options.shutdownTimeoutMilliseconds =
            std::max<std::int64_t>(0, _options.shutdownTimeoutMilliseconds);
        Detail::registerProcessDependencyGraphProvider(this, [this] {
            return dependencyGraph();
        });
        Detail::registerProcessDesiredStateMaintenanceProvider(
            this, [this](std::uint64_t expectedGeneration) {
                return recommitDesiredState(expectedGeneration);
            });
    }

    ~Impl()
    {
        Detail::unregisterProcessDesiredStateMaintenanceProvider(this);
        Detail::unregisterProcessDependencyGraphProvider(this);
        stopAll();
    }

    std::size_t start(const std::string& configurationPath, const std::string& rootDirectory)
    {
        stopAll();
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            _configured.clear();
            _desiredStateStore.reset();
            _desiredStateGeneration = 0;
            _desiredStateHealthy = true;
            _desiredStateRecovered = false;
            _desiredStateStatus = "disabled";
            _desiredStateIntegrityState = "disabled";
            _desiredStatePrimaryValid = true;
            _desiredStatePreviousAvailable = false;
            _desiredStatePreviousValid = false;
            _desiredStateLastIntegrityCheckEpochMicroseconds = 0;
            _desiredStateNextScrub = {};
            ++_configurationGeneration;
        }
        Poco::File configurationFile(configurationPath);
        if (!configurationFile.exists())
        {
            _logger.warning("Subprocess configuration not found: %s", configurationPath);
            return 0;
        }

        Poco::AutoPtr<Poco::Util::PropertyFileConfiguration> configuration =
            new Poco::Util::PropertyFileConfiguration(configurationPath);
        const int count = std::max(0, configuration->getInt("subprocess.count", 0));
        const auto supervisionInterval = configuration->getInt64(
            "subprocess.supervisionIntervalMilliseconds", 100);
        if (supervisionInterval < 10 || supervisionInterval > 60000)
            throw Poco::InvalidArgumentException(
                "Subprocess supervision interval must be between 10 and 60000 milliseconds");
        _supervisionIntervalMilliseconds = supervisionInterval;

        std::unique_ptr<Detail::ProcessDesiredStateStore> desiredStateStore;
        std::int64_t desiredStateScrubIntervalMilliseconds = 60000;
        if (configuration->getBool(
                "subprocess.desiredStatePersistence.enabled", false))
        {
            const auto relativePath = configuration->getString(
                "subprocess.desiredStatePersistence.path",
                "data/process-desired-state.json");
            if (relativePath.empty() || Poco::Path(relativePath).isDirectory())
                throw Poco::InvalidArgumentException(
                    "Process desired-state path must name a relative file",
                    relativePath);
            desiredStateStore =
                std::make_unique<Detail::ProcessDesiredStateStore>(
                    resolveRelativePath(rootDirectory, relativePath));
            desiredStateScrubIntervalMilliseconds = configuration->getInt64(
                "subprocess.desiredStatePersistence.scrubIntervalMilliseconds",
                60000);
            if (desiredStateScrubIntervalMilliseconds < 10 ||
                desiredStateScrubIntervalMilliseconds > 86400000)
                throw Poco::InvalidArgumentException(
                    "Process desired-state scrub interval must be between 10 and 86400000 milliseconds");
        }

        try
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            _configured.clear();
            _desiredStateStore = std::move(desiredStateStore);
            _desiredStateScrubIntervalMilliseconds =
                desiredStateScrubIntervalMilliseconds;
            for (int index = 0; index < count; ++index)
            {
                const std::string prefix = "subprocess." + std::to_string(index) + ".";
                if (!configuration->getBool(prefix + "enabled", true))
                    continue;

                const std::string relativePath = configuration->getString(prefix + "path");
                const std::string executable = resolveRelativePath(rootDirectory, relativePath);
                Poco::File executableFile(executable);
                if (!executableFile.exists() || !executableFile.isFile())
                    throw Poco::FileNotFoundException("Subprocess executable", executable);

                Poco::Process::Args arguments;
                const int argumentCount =
                    std::max(0, configuration->getInt(prefix + "argument.count", 0));
                for (int argument = 0; argument < argumentCount; ++argument)
                {
                    arguments.push_back(
                        configuration->getString(prefix + "argument." + std::to_string(argument)));
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
                if (name.empty())
                    throw Poco::InvalidArgumentException(
                        "Subprocess name must not be empty");
                std::string location = configuration->getString(prefix + "location", "local");
                std::transform(location.begin(), location.end(), location.begin(),
                               [](unsigned char value)
                               { return static_cast<char>(std::tolower(value)); });
                if (location != "local" && location != "remote")
                    throw Poco::InvalidArgumentException(
                        "Subprocess location must be local or remote", location);
                const bool required = configuration->getBool(prefix + "required", true);
                if (findConfigured(name) != _configured.end())
                    throw Poco::InvalidArgumentException(
                        "Duplicate subprocess name", name);

                const int dependencyCount = configuration->getInt(
                    prefix + "dependency.count", 0);
                if (dependencyCount < 0 || dependencyCount > count)
                    throw Poco::InvalidArgumentException(
                        "Invalid subprocess dependency count", name);
                std::vector<std::string> dependencies;
                dependencies.reserve(static_cast<std::size_t>(dependencyCount));
                for (int dependency = 0; dependency < dependencyCount; ++dependency)
                {
                    const auto dependencyName = configuration->getString(
                        prefix + "dependency." + std::to_string(dependency));
                    if (dependencyName.empty() ||
                        std::find(dependencies.begin(), dependencies.end(),
                                  dependencyName) != dependencies.end())
                        throw Poco::InvalidArgumentException(
                            "Invalid or duplicate subprocess dependency",
                            dependencyName);
                    dependencies.push_back(dependencyName);
                }

                std::string restartPolicy = configuration->getString(
                    prefix + "restartPolicy", "never");
                std::transform(restartPolicy.begin(), restartPolicy.end(),
                               restartPolicy.begin(), [](unsigned char value) {
                                   return static_cast<char>(std::tolower(value));
                               });
                if (restartPolicy != "never" &&
                    restartPolicy != "on-failure" &&
                    restartPolicy != "always")
                    throw Poco::InvalidArgumentException(
                        "Subprocess restartPolicy must be never, on-failure or always",
                        restartPolicy);

                const auto maximumRestartAttempts = configuration->getInt64(
                    prefix + "restartMaximumAttempts",
                    restartPolicy == "never" ? 0 : 5);
                const auto initialBackoff = configuration->getInt64(
                    prefix + "restartInitialBackoffMilliseconds", 250);
                const auto maximumBackoff = configuration->getInt64(
                    prefix + "restartMaximumBackoffMilliseconds", 30000);
                const auto backoffMultiplier = configuration->getDouble(
                    prefix + "restartBackoffMultiplier", 2.0);
                const auto resetAfter = configuration->getInt64(
                    prefix + "restartResetAfterMilliseconds", 60000);
                const std::string readinessRelative = configuration->getString(
                    prefix + "readinessFile", "");
                const auto readinessTimeout = configuration->getInt64(
                    prefix + "readinessTimeoutMilliseconds",
                    readinessRelative.empty() ? 0 : 10000);
                const auto heartbeatTimeout = configuration->getInt64(
                    prefix + "heartbeatTimeoutMilliseconds", 0);
                if (maximumRestartAttempts < 0 || maximumRestartAttempts > 1000000 ||
                    initialBackoff < 10 || initialBackoff > 3600000 ||
                    maximumBackoff < initialBackoff || maximumBackoff > 3600000 ||
                    !std::isfinite(backoffMultiplier) || backoffMultiplier < 1.0 ||
                    backoffMultiplier > 100.0 || resetAfter < 0 ||
                    resetAfter > 86400000)
                    throw Poco::InvalidArgumentException(
                        "Invalid subprocess restart policy bounds", name);
                if (readinessRelative.empty())
                {
                    if (readinessTimeout != 0 || heartbeatTimeout != 0)
                        throw Poco::InvalidArgumentException(
                            "Subprocess readiness/heartbeat timeout requires readinessFile",
                            name);
                }
                else if (location != "local" || readinessTimeout < 10 ||
                         readinessTimeout > 3600000 || heartbeatTimeout < 0 ||
                         heartbeatTimeout > 3600000 ||
                         (heartbeatTimeout > 0 &&
                          heartbeatTimeout < supervisionInterval * 2))
                    throw Poco::InvalidArgumentException(
                        "Invalid subprocess readiness/heartbeat policy bounds", name);

                ConfiguredProcess configured;
                configured.name = name;
                configured.executable = executable;
                configured.arguments = std::move(arguments);
                configured.initialDirectory = initialDirectory;
                configured.location = location;
                configured.required = required;
                configured.restartPolicy = restartPolicy;
                configured.maximumRestartAttempts =
                    static_cast<std::uint64_t>(maximumRestartAttempts);
                configured.initialBackoffMilliseconds = initialBackoff;
                configured.maximumBackoffMilliseconds = maximumBackoff;
                configured.backoffMultiplier = backoffMultiplier;
                configured.resetAfterMilliseconds = resetAfter;
                configured.nextBackoffMilliseconds = initialBackoff;
                if (!readinessRelative.empty())
                    configured.readinessFile = resolveRelativePath(
                        rootDirectory, readinessRelative);
                configured.readinessTimeoutMilliseconds = readinessTimeout;
                configured.heartbeatTimeoutMilliseconds = heartbeatTimeout;
                configured.dependencies = std::move(dependencies);
                configured.desiredRunning = location == "local";
                configured.recoveryState =
                    location == "local" ? "starting" : "remote";
                _configured.push_back(std::move(configured));
            }
            validateAndOrderDependencies();
            restoreDesiredStatesLocked();
            for (auto& configured : _configured)
            {
                if (configured.location == "remote")
                {
                    _logger.information(
                        "Registered remote subprocess '%s'; local launch skipped.",
                        configured.name);
                }
            }
            launchEligibleProcesses(std::chrono::steady_clock::now(), true);
        }
        catch (...)
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            for (auto iterator = _running.rbegin(); iterator != _running.rend(); ++iterator)
                stopProcess(*iterator);
            _running.clear();
            _configured.clear();
            _desiredStateStore.reset();
            _desiredStateGeneration = 0;
            _desiredStateHealthy = true;
            _desiredStateRecovered = false;
            _desiredStateStatus = "disabled";
            _desiredStateIntegrityState = "disabled";
            _desiredStatePrimaryValid = true;
            _desiredStatePreviousAvailable = false;
            _desiredStatePreviousValid = false;
            _desiredStateLastIntegrityCheckEpochMicroseconds = 0;
            _desiredStateNextScrub = {};
            throw;
        }
        std::size_t started = 0;
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            started = _running.size();
        }
        startSupervisor();
        return started;
    }

    void stopAll()
    {
        stopSupervisor();
        Poco::FastMutex::ScopedLock lock(_mutex);
        for (auto& configured : _configured)
        {
            configured.desiredRunning = false;
            configured.restartPending = false;
            if (configured.location == "local")
                configured.recoveryState = "stopped";
        }
        for (auto configured = _configured.rbegin();
             configured != _configured.rend(); ++configured)
        {
            const auto running = findRunning(configured->name);
            if (running != _running.end())
            {
                stopProcess(*running);
                _running.erase(running);
            }
        }
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
        const auto existing = findRunning(name);
        if (existing != _running.end() &&
            Poco::Process::isRunning(*existing->handle))
            return true;
        std::vector<std::pair<ConfiguredProcess*, bool>> previousDesiredStates;
        for (auto& candidate : _configured)
        {
            if (candidate.location != "local" ||
                (candidate.name != name &&
                 !dependsTransitivelyOn(*configured, candidate.name)))
                continue;
            previousDesiredStates.emplace_back(&candidate,
                                                candidate.desiredRunning);
            candidate.desiredRunning = true;
        }
        try
        {
            persistDesiredStatesLocked();
        }
        catch (...)
        {
            for (const auto& [candidate, desiredRunning] :
                 previousDesiredStates)
                candidate->desiredRunning = desiredRunning;
            throw;
        }
        for (const auto& [candidate, ignored] : previousDesiredStates)
        {
            (void)ignored;
            candidate->restartPending = false;
            candidate->consecutiveRestartAttempts = 0;
            candidate->nextBackoffMilliseconds =
                candidate->initialBackoffMilliseconds;
            const auto running = findRunning(candidate->name);
            if (running != _running.end() &&
                !Poco::Process::isRunning(*running->handle))
            {
                running->handle->wait();
                _running.erase(running);
            }
            if (findRunning(candidate->name) == _running.end())
                candidate->recoveryState = candidate->dependencies.empty()
                    ? "starting" : "waiting-dependency";
        }
        launchEligibleProcesses(std::chrono::steady_clock::now(), true);
        return true;
    }

    bool stopOne(const std::string& name)
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        const auto configured = findConfigured(name);
        if (configured == _configured.end() || configured->location != "local")
            return false;
        const bool previousDesiredRunning = configured->desiredRunning;
        configured->desiredRunning = false;
        try
        {
            persistDesiredStatesLocked();
        }
        catch (...)
        {
            configured->desiredRunning = previousDesiredRunning;
            throw;
        }
        for (auto candidate = _configured.rbegin();
             candidate != _configured.rend(); ++candidate)
        {
            if (candidate->name != name &&
                !dependsTransitivelyOn(*candidate, name))
                continue;
            if (candidate->name == name)
            {
                candidate->recoveryState = "stopped";
                candidate->consecutiveRestartAttempts = 0;
                candidate->nextBackoffMilliseconds =
                    candidate->initialBackoffMilliseconds;
            }
            else if (candidate->desiredRunning)
                candidate->recoveryState = "dependency-failed";
            candidate->restartPending = false;
            const auto running = findRunning(candidate->name);
            if (running != _running.end())
            {
                stopProcess(*running);
                _running.erase(running);
            }
        }
        return true;
    }

    bool restartOne(const std::string& name)
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        const auto configured = findConfigured(name);
        if (configured == _configured.end() || configured->location != "local")
            return false;
        std::vector<std::pair<ConfiguredProcess*, bool>> previousDesiredStates;
        for (auto& candidate : _configured)
        {
            if (candidate.location != "local" ||
                (candidate.name != name &&
                 !dependsTransitivelyOn(*configured, candidate.name)))
                continue;
            previousDesiredStates.emplace_back(&candidate,
                                                candidate.desiredRunning);
            candidate.desiredRunning = true;
        }
        try
        {
            persistDesiredStatesLocked();
        }
        catch (...)
        {
            for (const auto& [candidate, desiredRunning] :
                 previousDesiredStates)
                candidate->desiredRunning = desiredRunning;
            throw;
        }

        for (auto candidate = _configured.rbegin();
             candidate != _configured.rend(); ++candidate)
        {
            if (candidate->name != name &&
                !dependsTransitivelyOn(*candidate, name))
                continue;
            candidate->restartPending = false;
            if (candidate->name == name)
            {
                candidate->consecutiveRestartAttempts = 0;
                candidate->nextBackoffMilliseconds =
                    candidate->initialBackoffMilliseconds;
            }
            const auto running = findRunning(candidate->name);
            if (running != _running.end())
            {
                stopProcess(*running);
                _running.erase(running);
            }
            if (candidate->desiredRunning)
                candidate->recoveryState = candidate->name == name
                    ? (candidate->dependencies.empty()
                           ? "starting" : "waiting-dependency")
                    : "waiting-dependency";
        }
        launchEligibleProcesses(std::chrono::steady_clock::now(), true);
        return true;
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
            info.required = configured.required;
            const auto running = findRunning(configured.name);
            if (running != _running.end() && Poco::Process::isRunning(*running->handle))
            {
                info.state = configured.recoveryState;
                info.processId = static_cast<unsigned long>(running->handle->id());
            }
            else if (configured.location == "local")
                info.state = configured.recoveryState;
            result.push_back(std::move(info));
        }
        return result;
    }

    std::size_t runningCount() const
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        return static_cast<std::size_t>(
            std::count_if(_running.begin(), _running.end(), [](const RunningProcess& process)
                          { return Poco::Process::isRunning(*process.handle); }));
    }

    ProcessDependencyGraphSnapshot dependencyGraph() const
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        ProcessDependencyGraphSnapshot snapshot;
        snapshot.available = true;
        snapshot.generation = _configurationGeneration;
        snapshot.desiredStatePersistence.enabled =
            static_cast<bool>(_desiredStateStore);
        snapshot.desiredStatePersistence.healthy = _desiredStateHealthy;
        snapshot.desiredStatePersistence.leaseHeld =
            _desiredStateStore && _desiredStateStore->leaseHeld();
        snapshot.desiredStatePersistence.recoveredFromPrevious =
            _desiredStateRecovered;
        snapshot.desiredStatePersistence.primaryValid =
            _desiredStatePrimaryValid;
        snapshot.desiredStatePersistence.previousAvailable =
            _desiredStatePreviousAvailable;
        snapshot.desiredStatePersistence.previousValid =
            _desiredStatePreviousValid;
        snapshot.desiredStatePersistence.generation =
            _desiredStateGeneration;
        snapshot.desiredStatePersistence.lastIntegrityCheckEpochMicroseconds =
            _desiredStateLastIntegrityCheckEpochMicroseconds;
        snapshot.desiredStatePersistence.state = _desiredStateStatus;
        snapshot.desiredStatePersistence.integrityState =
            _desiredStateIntegrityState;
        snapshot.nodes.reserve(_configured.size());
        for (const auto& configured : _configured)
        {
            ProcessDependencyNode node;
            node.name = configured.name;
            node.location = configured.location;
            node.state = configured.recoveryState;
            node.manageable = configured.location == "local";
            node.required = configured.required;
            node.desiredRunning = configured.desiredRunning;
            node.dependencies = configured.dependencies;
            const auto running = findRunning(configured.name);
            if (running != _running.end() &&
                Poco::Process::isRunning(*running->handle))
                node.processId = static_cast<unsigned long>(running->handle->id());
            snapshot.nodes.push_back(std::move(node));
        }
        return snapshot;
    }

    ProcessDesiredStateRecommitResult recommitDesiredState(
        std::uint64_t expectedGeneration)
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        ProcessDesiredStateRecommitResult result;
        result.expectedGeneration = expectedGeneration;
        result.previousGeneration = _desiredStateGeneration;
        result.generation = _desiredStateGeneration;
        result.healthy = _desiredStateHealthy;
        result.integrityState = _desiredStateIntegrityState;
        if (!_desiredStateStore)
        {
            result.code = "persistence-disabled";
            return result;
        }
        if (expectedGeneration != _desiredStateGeneration)
        {
            result.code = "generation-conflict";
            return result;
        }

        refreshDesiredStateIntegrityLocked(true);
        result.healthy = _desiredStateHealthy;
        result.integrityState = _desiredStateIntegrityState;
        if (_desiredStateHealthy)
        {
            result.accepted = true;
            result.code = "already-healthy";
            return result;
        }

        persistDesiredStatesLocked();
        result.accepted = true;
        result.changed = true;
        result.generation = _desiredStateGeneration;
        result.healthy = _desiredStateHealthy;
        result.integrityState = _desiredStateIntegrityState;
        result.code = _desiredStateHealthy
            ? "recommitted" : "recommitted-degraded";
        return result;
    }

  private:
    enum class DependencyAvailability
    {
        Ready,
        Waiting,
        Failed
    };

    std::map<std::string, bool> desiredStatesLocked() const
    {
        std::map<std::string, bool> states;
        for (const auto& configured : _configured)
        {
            if (configured.location == "local")
                states.emplace(configured.name, configured.desiredRunning);
        }
        return states;
    }

    void refreshDesiredStateIntegrityLocked(bool logTransitions)
    {
        if (!_desiredStateStore)
            return;
        const bool wasHealthy = _desiredStateHealthy;
        const auto integrity = _desiredStateStore->inspect(
            _desiredStateGeneration, desiredStatesLocked());
        _desiredStatePrimaryValid = integrity.primaryValid;
        _desiredStatePreviousAvailable = integrity.previousAvailable;
        _desiredStatePreviousValid = integrity.previousValid;
        _desiredStateLastIntegrityCheckEpochMicroseconds =
            static_cast<std::uint64_t>(Poco::Timestamp().epochMicroseconds());
        _desiredStateHealthy = integrity.primaryValid &&
            (!integrity.previousAvailable || integrity.previousValid);
        if (!integrity.primaryValid)
            _desiredStateIntegrityState = "primary-invalid";
        else if (integrity.previousAvailable && !integrity.previousValid)
            _desiredStateIntegrityState = "previous-invalid";
        else
            _desiredStateIntegrityState = "healthy";
        _desiredStateStatus = _desiredStateHealthy
            ? (_desiredStateRecovered ? "recovered" : "healthy")
            : "degraded";
        _desiredStateNextScrub = std::chrono::steady_clock::now() +
            std::chrono::milliseconds(
                _desiredStateScrubIntervalMilliseconds);

        if (logTransitions && wasHealthy != _desiredStateHealthy)
        {
            if (_desiredStateHealthy)
                _logger.information(
                    "Process desired-state integrity returned to healthy at generation %Lu.",
                    static_cast<unsigned long long>(
                        _desiredStateGeneration));
            else
                _logger.critical(
                    "Process desired-state integrity degraded at generation %Lu (%s).",
                    static_cast<unsigned long long>(
                        _desiredStateGeneration),
                    _desiredStateIntegrityState);
        }
    }

    void scrubDesiredStateLocked(
        std::chrono::steady_clock::time_point now)
    {
        if (!_desiredStateStore ||
            (_desiredStateNextScrub.time_since_epoch().count() != 0 &&
             now < _desiredStateNextScrub))
            return;
        try
        {
            refreshDesiredStateIntegrityLocked(true);
        }
        catch (const Poco::Exception& exception)
        {
            const bool wasHealthy = _desiredStateHealthy;
            _desiredStateHealthy = false;
            _desiredStatePrimaryValid = false;
            _desiredStateIntegrityState = "inspection-failed";
            _desiredStateStatus = "degraded";
            _desiredStateLastIntegrityCheckEpochMicroseconds =
                static_cast<std::uint64_t>(
                    Poco::Timestamp().epochMicroseconds());
            _desiredStateNextScrub = now + std::chrono::milliseconds(
                _desiredStateScrubIntervalMilliseconds);
            if (wasHealthy)
                _logger.critical(
                    "Process desired-state integrity inspection failed: %s",
                    exception.displayText());
        }
    }

    void persistDesiredStatesLocked()
    {
        if (!_desiredStateStore)
            return;
        if (_desiredStateGeneration ==
            std::numeric_limits<std::uint64_t>::max())
        {
            _desiredStateHealthy = false;
            _desiredStateStatus = "degraded";
            _desiredStateIntegrityState = "generation-exhausted";
            throw Poco::RangeException(
                "Process desired-state generation is exhausted");
        }
        const auto nextGeneration = _desiredStateGeneration + 1;
        try
        {
            _desiredStateStore->save(nextGeneration, desiredStatesLocked());
        }
        catch (...)
        {
            _desiredStateHealthy = false;
            _desiredStateStatus = "degraded";
            _desiredStateIntegrityState = "commit-failed";
            throw;
        }
        _desiredStateGeneration = nextGeneration;
        refreshDesiredStateIntegrityLocked(true);
    }

    void persistDesiredStatesBestEffortLocked(const std::string& reason)
    {
        try
        {
            persistDesiredStatesLocked();
        }
        catch (const Poco::Exception& exception)
        {
            _logger.critical(
                "Cannot persist process desired state after %s: %s",
                reason, exception.displayText());
        }
        catch (const std::exception& exception)
        {
            _logger.critical(
                "Cannot persist process desired state after %s: %s",
                reason, std::string(exception.what()));
        }
    }

    void restoreDesiredStatesLocked()
    {
        if (!_desiredStateStore)
            return;
        _desiredStateStore->acquireLease();
        const auto snapshot = _desiredStateStore->load();
        bool normalized = !snapshot.available;
        _desiredStateGeneration = snapshot.generation;
        _desiredStateHealthy = true;
        _desiredStateRecovered = snapshot.recovered;
        _desiredStateStatus = snapshot.recovered
            ? "recovered" : "healthy";
        if (snapshot.available)
        {
            for (auto& configured : _configured)
            {
                if (configured.location != "local")
                    continue;
                const auto state = snapshot.states.find(configured.name);
                if (state == snapshot.states.end())
                {
                    normalized = true;
                    continue;
                }
                configured.desiredRunning = state->second;
                configured.recoveryState = state->second
                    ? (configured.dependencies.empty()
                           ? "starting" : "waiting-dependency")
                    : "stopped";
            }
            if (snapshot.states != desiredStatesLocked())
                normalized = true;
            if (snapshot.recovered)
            {
                normalized = true;
                _logger.warning(
                    "Recovered process desired state from %s after the primary snapshot was unavailable or invalid.",
                    snapshot.recoveredFrom);
            }
            else
            {
                _logger.information(
                    "Loaded process desired state generation %Lu from %s.",
                    static_cast<unsigned long long>(snapshot.generation),
                    _desiredStateStore->path());
            }
        }
        if (normalized)
            persistDesiredStatesLocked();
        else
            refreshDesiredStateIntegrityLocked(false);
    }

    void validateAndOrderDependencies()
    {
        for (const auto& process : _configured)
        {
            if (process.location == "remote" && !process.dependencies.empty())
                throw Poco::InvalidArgumentException(
                    "Remote subprocess cannot declare managed dependencies",
                    process.name);
            for (const auto& dependencyName : process.dependencies)
            {
                if (dependencyName == process.name)
                    throw Poco::InvalidArgumentException(
                        "Subprocess cannot depend on itself", process.name);
                const auto dependency = findConfigured(dependencyName);
                if (dependency == _configured.end())
                    throw Poco::InvalidArgumentException(
                        "Unknown subprocess dependency", dependencyName);
                if (dependency->location != "local")
                    throw Poco::InvalidArgumentException(
                        "Managed subprocess dependency must be local",
                        dependencyName);
            }
        }

        std::vector<std::size_t> indegrees;
        indegrees.reserve(_configured.size());
        for (const auto& process : _configured)
            indegrees.push_back(process.dependencies.size());
        std::vector<bool> selected(_configured.size(), false);
        std::vector<std::size_t> order;
        order.reserve(_configured.size());
        while (order.size() != _configured.size())
        {
            std::size_t next = _configured.size();
            for (std::size_t index = 0; index < _configured.size(); ++index)
            {
                if (!selected[index] && indegrees[index] == 0)
                {
                    next = index;
                    break;
                }
            }
            if (next == _configured.size())
                throw Poco::InvalidArgumentException(
                    "Subprocess dependency graph contains a cycle");
            selected[next] = true;
            order.push_back(next);
            const auto& resolvedName = _configured[next].name;
            for (std::size_t index = 0; index < _configured.size(); ++index)
            {
                if (selected[index])
                    continue;
                const auto& dependencies = _configured[index].dependencies;
                if (std::find(dependencies.begin(), dependencies.end(),
                              resolvedName) != dependencies.end())
                    --indegrees[index];
            }
        }

        std::vector<ConfiguredProcess> ordered;
        ordered.reserve(_configured.size());
        for (const auto index : order)
            ordered.push_back(std::move(_configured[index]));
        _configured = std::move(ordered);
    }

    bool dependsTransitivelyOn(const ConfiguredProcess& process,
                               const std::string& dependencyName) const
    {
        for (const auto& directDependency : process.dependencies)
        {
            if (directDependency == dependencyName)
                return true;
            const auto dependency = findConfigured(directDependency);
            if (dependency != _configured.end() &&
                dependsTransitivelyOn(*dependency, dependencyName))
                return true;
        }
        return false;
    }

    DependencyAvailability dependencyAvailability(
        const ConfiguredProcess& process) const
    {
        bool failed = false;
        bool waiting = false;
        for (const auto& dependencyName : process.dependencies)
        {
            const auto dependency = findConfigured(dependencyName);
            if (dependency == _configured.end())
                return DependencyAvailability::Failed;
            const auto running = findRunning(dependencyName);
            if (dependency->recoveryState == "running" &&
                running != _running.end() &&
                Poco::Process::isRunning(*running->handle))
                continue;
            if (!dependency->desiredRunning ||
                dependency->recoveryState == "failed" ||
                dependency->recoveryState == "exited" ||
                dependency->recoveryState == "stopped" ||
                dependency->recoveryState == "dependency-failed")
                failed = true;
            else
                waiting = true;
        }
        if (failed)
            return DependencyAvailability::Failed;
        return waiting ? DependencyAvailability::Waiting
                       : DependencyAvailability::Ready;
    }

    void launchEligibleProcesses(
        std::chrono::steady_clock::time_point now,
        bool propagateExceptions)
    {
        for (auto& configured : _configured)
        {
            if (configured.location != "local" ||
                !configured.desiredRunning ||
                findRunning(configured.name) != _running.end())
                continue;
            const auto availability = dependencyAvailability(configured);
            if (availability != DependencyAvailability::Ready)
            {
                configured.recoveryState =
                    availability == DependencyAvailability::Failed
                    ? "dependency-failed" : "waiting-dependency";
                continue;
            }
            if (configured.restartPending && configured.nextRestart > now)
            {
                configured.recoveryState = "restart-pending";
                continue;
            }
            const bool retry = configured.restartPending;
            if (retry)
                ++configured.consecutiveRestartAttempts;
            try
            {
                launch(configured);
            }
            catch (const Poco::Exception& exception)
            {
                if (propagateExceptions)
                    throw;
                _logger.error(
                    "Subprocess '%s' launch failed: %s",
                    configured.name, exception.displayText());
                if (configured.restartPolicy == "never")
                {
                    configured.desiredRunning = false;
                    configured.restartPending = false;
                    configured.recoveryState = "failed";
                    persistDesiredStatesBestEffortLocked(
                        "non-restartable launch failure");
                }
                else
                    scheduleRestart(configured, now);
            }
            catch (const std::exception& exception)
            {
                if (propagateExceptions)
                    throw;
                _logger.error(
                    "Subprocess '%s' launch failed: %s",
                    configured.name, std::string(exception.what()));
                if (configured.restartPolicy == "never")
                {
                    configured.desiredRunning = false;
                    configured.restartPending = false;
                    configured.recoveryState = "failed";
                    persistDesiredStatesBestEffortLocked(
                        "non-restartable launch failure");
                }
                else
                    scheduleRestart(configured, now);
            }
        }
    }

    void launch(ConfiguredProcess& process)
    {
        const auto readinessBaseline = process.readinessFile.empty()
            ? FileSignal{}
            : fileSignal(process.readinessFile);
        _logger.information("Starting local subprocess '%s': %s", process.name, process.executable);
        auto handle = std::make_unique<Poco::ProcessHandle>(
            Poco::Process::launch(process.executable, process.arguments, process.initialDirectory));
        _logger.information("Subprocess '%s' started with PID %d.", process.name,
                            static_cast<int>(handle->id()));
        const auto started = std::chrono::steady_clock::now();
        RunningProcess running;
        running.name = process.name;
        running.handle = std::move(handle);
        running.started = started;
        running.ready = process.readinessFile.empty();
        running.readyAt = started;
        running.lastSignalObserved = started;
        running.signal = readinessBaseline;
        _running.push_back(std::move(running));
        process.restartPending = false;
        process.recoveryState = process.readinessFile.empty()
            ? "running" : "starting";
    }

    void scheduleRestart(ConfiguredProcess& process,
                         std::chrono::steady_clock::time_point now)
    {
        if (process.consecutiveRestartAttempts >=
            process.maximumRestartAttempts)
        {
            process.desiredRunning = false;
            process.restartPending = false;
            process.recoveryState = "failed";
            persistDesiredStatesBestEffortLocked(
                "restart budget exhaustion");
            _logger.error(
                "Subprocess '%s' exhausted its restart budget after %Lu attempt(s).",
                process.name,
                static_cast<unsigned long long>(
                    process.consecutiveRestartAttempts));
            return;
        }
        process.nextRestart = now + std::chrono::milliseconds(
            process.nextBackoffMilliseconds);
        process.restartPending = true;
        process.recoveryState = "restart-pending";
        _logger.warning(
            "Subprocess '%s' scheduled for restart in %Ld ms (%Lu/%Lu).",
            process.name,
            static_cast<long long>(process.nextBackoffMilliseconds),
            static_cast<unsigned long long>(
                process.consecutiveRestartAttempts + 1),
            static_cast<unsigned long long>(process.maximumRestartAttempts));
        const auto scaled = static_cast<double>(
            process.nextBackoffMilliseconds) * process.backoffMultiplier;
        process.nextBackoffMilliseconds = std::min(
            process.maximumBackoffMilliseconds,
            static_cast<std::int64_t>(scaled));
    }

    void recordExit(ConfiguredProcess& configured, RunningProcess& running,
                    int exitCode,
                    std::chrono::steady_clock::time_point now)
    {
        const auto stableSince = configured.readinessFile.empty()
            ? running.started : running.readyAt;
        if (running.ready &&
            (configured.resetAfterMilliseconds == 0 ||
             now - stableSince >= std::chrono::milliseconds(
                 configured.resetAfterMilliseconds)))
        {
            configured.consecutiveRestartAttempts = 0;
            configured.nextBackoffMilliseconds =
                configured.initialBackoffMilliseconds;
        }
        _logger.warning("Subprocess '%s' exited with code %d.",
                        configured.name, exitCode);
        const bool restart = configured.desiredRunning &&
            (configured.restartPolicy == "always" ||
             (configured.restartPolicy == "on-failure" && exitCode != 0));
        if (!restart)
        {
            const bool desiredBeforeExit = configured.desiredRunning;
            configured.desiredRunning = false;
            configured.restartPending = false;
            configured.recoveryState = "exited";
            if (desiredBeforeExit)
                persistDesiredStatesBestEffortLocked(
                    "terminal subprocess exit");
            return;
        }
        scheduleRestart(configured, now);
    }

    bool superviseSignals(ConfiguredProcess& configured,
                          RunningProcess& running,
                          std::chrono::steady_clock::time_point now)
    {
        if (configured.readinessFile.empty())
            return true;
        const auto signal = fileSignal(configured.readinessFile);
        if (signal.available && !sameSignal(signal, running.signal))
        {
            running.signal = signal;
            running.lastSignalObserved = now;
            if (!running.ready)
            {
                running.ready = true;
                running.readyAt = now;
                configured.recoveryState = "running";
                _logger.information(
                    "Subprocess '%s' passed startup readiness.",
                    configured.name);
            }
        }
        if (!running.ready &&
            now - running.started >= std::chrono::milliseconds(
                configured.readinessTimeoutMilliseconds))
        {
            _logger.error(
                "Subprocess '%s' startup readiness timed out after %Ld ms.",
                configured.name,
                static_cast<long long>(
                    configured.readinessTimeoutMilliseconds));
            return false;
        }
        if (running.ready && configured.heartbeatTimeoutMilliseconds > 0 &&
            now - running.lastSignalObserved >= std::chrono::milliseconds(
                configured.heartbeatTimeoutMilliseconds))
        {
            _logger.error(
                "Subprocess '%s' heartbeat timed out after %Ld ms.",
                configured.name,
                static_cast<long long>(
                    configured.heartbeatTimeoutMilliseconds));
            return false;
        }
        return true;
    }

    void failSignalGate(ConfiguredProcess& configured,
                        RunningProcess& running)
    {
        stopProcess(running);
        if (configured.desiredRunning &&
            configured.restartPolicy != "never")
            scheduleRestart(configured, std::chrono::steady_clock::now());
        else
        {
            const bool desiredBeforeFailure = configured.desiredRunning;
            configured.desiredRunning = false;
            configured.restartPending = false;
            configured.recoveryState = "failed";
            if (desiredBeforeFailure)
                persistDesiredStatesBestEffortLocked(
                    "health-signal failure");
        }
    }

    void supervise()
    {
        while (!_supervisionStop.tryWait(
            static_cast<long>(_supervisionIntervalMilliseconds)))
        {
            try
            {
                Poco::FastMutex::ScopedLock lock(_mutex);
                const auto now = std::chrono::steady_clock::now();
                scrubDesiredStateLocked(now);
                for (auto& configured : _configured)
                {
                    if (configured.location != "local")
                        continue;
                    auto running = findRunning(configured.name);
                    if (running != _running.end() &&
                        !Poco::Process::isRunning(*running->handle))
                    {
                        const int exitCode = running->handle->wait();
                        recordExit(configured, *running, exitCode, now);
                        _running.erase(running);
                        running = _running.end();
                    }
                    const auto availability =
                        dependencyAvailability(configured);
                    if (availability != DependencyAvailability::Ready)
                    {
                        if (running != _running.end())
                        {
                            _logger.warning(
                                "Stopping subprocess '%s' because a dependency is unavailable.",
                                configured.name);
                            stopProcess(*running);
                            _running.erase(running);
                            running = _running.end();
                        }
                        if (configured.desiredRunning)
                            configured.recoveryState =
                                availability == DependencyAvailability::Failed
                                ? "dependency-failed" : "waiting-dependency";
                        continue;
                    }
                    if (running != _running.end() &&
                        !superviseSignals(configured, *running, now))
                    {
                        failSignalGate(configured, *running);
                        _running.erase(running);
                        running = _running.end();
                    }
                }
                launchEligibleProcesses(now, false);
            }
            catch (const Poco::Exception& exception)
            {
                _logger.error("Subprocess supervision failed: %s",
                              exception.displayText());
            }
            catch (const std::exception& exception)
            {
                _logger.error("Subprocess supervision failed: %s",
                              std::string(exception.what()));
            }
        }
    }

    void startSupervisor()
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        const bool hasLocal = std::any_of(
            _configured.begin(), _configured.end(),
            [](const ConfiguredProcess& process) {
                return process.location == "local";
            });
        if (!hasLocal && !_desiredStateStore)
            return;
        _supervisionStop.reset();
        _supervisionThread = std::thread([this] { supervise(); });
    }

    void stopSupervisor()
    {
        _supervisionStop.set();
        if (_supervisionThread.joinable())
            _supervisionThread.join();
    }

    void stopProcess(RunningProcess& process)
    {
        if (!Poco::Process::isRunning(*process.handle))
        {
            process.handle->wait();
            return;
        }
        _logger.information("Stopping subprocess '%s' (PID %d).", process.name,
                            static_cast<int>(process.handle->id()));
        Poco::Process::requestTermination(process.handle->id());
        const Poco::Timestamp::TimeVal timeoutMicroseconds =
            _options.shutdownTimeoutMilliseconds * 1000;
        Poco::Timestamp started;
        while (Poco::Process::isRunning(*process.handle) && !started.isElapsed(timeoutMicroseconds))
            Poco::Thread::sleep(50);
#if defined(POCO_OS_FAMILY_WINDOWS)
        bool forceKilled = false;
#endif
        if (Poco::Process::isRunning(*process.handle))
        {
            _logger.warning("Subprocess '%s' did not stop in time; terminating it.", process.name);
            Poco::Process::kill(*process.handle);
#if defined(POCO_OS_FAMILY_WINDOWS)
            forceKilled = true;
#endif
        }
#if defined(POCO_OS_FAMILY_WINDOWS)
        if (!forceKilled)
#endif
        process.handle->wait();
    }

    std::vector<ConfiguredProcess>::iterator findConfigured(const std::string& name)
    {
        return std::find_if(_configured.begin(), _configured.end(),
                            [&](const ConfiguredProcess& process) { return process.name == name; });
    }

    std::vector<ConfiguredProcess>::const_iterator findConfigured(const std::string& name) const
    {
        return std::find_if(_configured.begin(), _configured.end(),
                            [&](const ConfiguredProcess& process) { return process.name == name; });
    }

    std::vector<RunningProcess>::iterator findRunning(const std::string& name)
    {
        return std::find_if(_running.begin(), _running.end(),
                            [&](const RunningProcess& process) { return process.name == name; });
    }

    std::vector<RunningProcess>::const_iterator findRunning(const std::string& name) const
    {
        return std::find_if(_running.begin(), _running.end(),
                            [&](const RunningProcess& process) { return process.name == name; });
    }

    Poco::Logger& _logger;
    SubprocessManagerOptions _options;
    std::vector<ConfiguredProcess> _configured;
    std::vector<RunningProcess> _running;
    mutable Poco::FastMutex _mutex;
    std::int64_t _supervisionIntervalMilliseconds{100};
    Poco::Event _supervisionStop;
    std::thread _supervisionThread;
    std::uint64_t _configurationGeneration{0};
    std::unique_ptr<Detail::ProcessDesiredStateStore> _desiredStateStore;
    std::uint64_t _desiredStateGeneration{0};
    std::int64_t _desiredStateScrubIntervalMilliseconds{60000};
    std::chrono::steady_clock::time_point _desiredStateNextScrub;
    bool _desiredStateHealthy{true};
    bool _desiredStateRecovered{false};
    bool _desiredStatePrimaryValid{true};
    bool _desiredStatePreviousAvailable{false};
    bool _desiredStatePreviousValid{false};
    std::uint64_t _desiredStateLastIntegrityCheckEpochMicroseconds{0};
    std::string _desiredStateStatus{"disabled"};
    std::string _desiredStateIntegrityState{"disabled"};
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
