#include "PocoDDS/ProcessManagement/SubprocessManager.h"

#include "Poco/AutoPtr.h"
#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/Logger.h"
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
                _logger.information("Starting subprocess %d/%d '%s': %s", index + 1, count, name,
                                    executable);
                auto handle = std::make_unique<Poco::ProcessHandle>(
                    Poco::Process::launch(executable, arguments, initialDirectory));
                _logger.information("Subprocess '%s' started with PID %d.", name,
                                    static_cast<int>(handle->id()));
                _running.push_back({name, std::move(handle)});
            }
        }
        catch (...)
        {
            stopAll();
            throw;
        }
        return _running.size();
    }

    void stopAll()
    {
        for (auto iterator = _running.rbegin(); iterator != _running.rend(); ++iterator)
        {
            auto& process = *iterator;
            if (!Poco::Process::isRunning(*process.handle))
                continue;

            _logger.information("Stopping subprocess '%s' (PID %d).", process.name,
                                static_cast<int>(process.handle->id()));
            Poco::Process::requestTermination(process.handle->id());
            const Poco::Timestamp::TimeVal timeoutMicroseconds =
                _options.shutdownTimeoutMilliseconds * 1000;
            Poco::Timestamp started;
            while (Poco::Process::isRunning(*process.handle) &&
                   !started.isElapsed(timeoutMicroseconds))
            {
                Poco::Thread::sleep(50);
            }
            if (Poco::Process::isRunning(*process.handle))
            {
                _logger.warning("Subprocess '%s' did not stop in time; terminating it.",
                                process.name);
                Poco::Process::kill(*process.handle);
            }
        }
        _running.clear();
    }

    std::size_t runningCount() const
    {
        return static_cast<std::size_t>(
            std::count_if(_running.begin(), _running.end(), [](const RunningProcess& process) {
                return Poco::Process::isRunning(*process.handle);
            }));
    }

  private:
    Poco::Logger& _logger;
    SubprocessManagerOptions _options;
    std::vector<RunningProcess> _running;
};

SubprocessManager::SubprocessManager(Poco::Logger& logger, SubprocessManagerOptions options)
    : _impl(new Impl(logger, options))
{
}

SubprocessManager::~SubprocessManager() { delete _impl; }

std::size_t SubprocessManager::startFromConfiguration(const std::string& configurationPath,
                                                      const std::string& processRootDirectory)
{
    return _impl->start(configurationPath, processRootDirectory);
}

void SubprocessManager::stopAll() { _impl->stopAll(); }
std::size_t SubprocessManager::runningCount() const { return _impl->runningCount(); }
} // namespace PocoDDS::ProcessManagement
