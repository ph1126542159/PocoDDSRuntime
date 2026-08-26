#include "PocoDDS/ProcessManagement/SubprocessManager.h"

#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/Logger.h>
#include <Poco/Path.h>
#include <Poco/TemporaryFile.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

namespace
{
using namespace std::chrono_literals;
using PocoDDS::ProcessManagement::SubprocessManager;

void require(bool condition, const std::string& message)
{
    if (!condition)
        throw std::runtime_error(message);
}

struct TemporaryWorkspace
{
    Poco::Path path{Poco::TemporaryFile::tempName()};

    TemporaryWorkspace()
    {
        path.makeDirectory();
        Poco::File(path).createDirectories();
    }

    ~TemporaryWorkspace()
    {
        try { Poco::File(path).remove(true); }
        catch (...) { }
    }
};

void writeConfiguration(const std::string& path,
                        const std::string& executable,
                        const std::string& policy,
                        std::uint64_t maximumAttempts,
                        int exitCode,
                        int delayMilliseconds,
                        const std::string& counterPath,
                        const std::string& readinessRelative = {},
                        const std::string& readinessArgument = {},
                        int readinessDelayMilliseconds = -1,
                        int heartbeatIntervalMilliseconds = 0,
                        int heartbeatDurationMilliseconds = 0,
                        int readinessTimeoutMilliseconds = 0,
                        int heartbeatTimeoutMilliseconds = 0)
{
    std::ofstream output(path, std::ios::trunc);
    require(static_cast<bool>(output), "failed to create subprocess fixture");
    output << "subprocess.count = 1\n"
           << "subprocess.supervisionIntervalMilliseconds = 20\n"
           << "subprocess.0.enabled = true\n"
           << "subprocess.0.name = recovery-probe\n"
           << "subprocess.0.location = local\n"
           << "subprocess.0.required = true\n"
           << "subprocess.0.path = " << executable << "\n"
           << "subprocess.0.workingDirectory = .\n"
           << "subprocess.0.restartPolicy = " << policy << "\n"
           << "subprocess.0.restartMaximumAttempts = "
           << maximumAttempts << "\n"
           << "subprocess.0.restartInitialBackoffMilliseconds = 25\n"
           << "subprocess.0.restartMaximumBackoffMilliseconds = 50\n"
           << "subprocess.0.restartBackoffMultiplier = 2.0\n"
           << "subprocess.0.restartResetAfterMilliseconds = 60000\n";
    if (!readinessRelative.empty())
        output << "subprocess.0.readinessFile = " << readinessRelative << "\n"
               << "subprocess.0.readinessTimeoutMilliseconds = "
               << readinessTimeoutMilliseconds << "\n"
               << "subprocess.0.heartbeatTimeoutMilliseconds = "
               << heartbeatTimeoutMilliseconds << "\n";
    else if (readinessTimeoutMilliseconds != 0 ||
             heartbeatTimeoutMilliseconds != 0)
        output << "subprocess.0.readinessTimeoutMilliseconds = "
               << readinessTimeoutMilliseconds << "\n"
               << "subprocess.0.heartbeatTimeoutMilliseconds = "
               << heartbeatTimeoutMilliseconds << "\n";
    output << "subprocess.0.argument.count = "
           << (readinessRelative.empty() ? 4 : 8) << "\n"
           << "subprocess.0.argument.0 = --supervision-child\n"
           << "subprocess.0.argument.1 = " << exitCode << "\n"
           << "subprocess.0.argument.2 = " << delayMilliseconds << "\n"
           << "subprocess.0.argument.3 = " << counterPath << "\n";
    if (!readinessRelative.empty())
        output << "subprocess.0.argument.4 = " << readinessArgument << "\n"
               << "subprocess.0.argument.5 = "
               << readinessDelayMilliseconds << "\n"
               << "subprocess.0.argument.6 = "
               << heartbeatIntervalMilliseconds << "\n"
               << "subprocess.0.argument.7 = "
               << heartbeatDurationMilliseconds << "\n";
    require(static_cast<bool>(output), "failed to write subprocess fixture");
}

PocoDDS::ProcessManagement::SubprocessInfo waitFor(
    SubprocessManager& manager,
    const std::function<bool(
        const PocoDDS::ProcessManagement::SubprocessInfo&)>& predicate,
    std::chrono::milliseconds timeout = 5s)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    do
    {
        const auto processes = manager.processes();
        if (processes.size() == 1 && predicate(processes.front()))
            return processes.front();
        std::this_thread::sleep_for(20ms);
    } while (std::chrono::steady_clock::now() < deadline);
    throw std::runtime_error("timed out waiting for subprocess recovery state");
}

void resetCounter(const std::string& path)
{
    std::ofstream output(path, std::ios::trunc);
    output << 0;
    require(static_cast<bool>(output), "failed to reset launch counter");
}

int readCounter(const std::string& path)
{
    std::ifstream input(path);
    int value = -1;
    input >> value;
    require(static_cast<bool>(input), "failed to read launch counter");
    return value;
}

void writeSignal(const std::string& path, std::int64_t value)
{
    std::ofstream output(path, std::ios::trunc);
    output << value << '\n';
}
} // namespace

int main(int argc, char** argv)
{
    if ((argc == 5 || argc == 9) &&
        std::string(argv[1]) == "--supervision-child")
    {
        int launches = 0;
        {
            std::ifstream input(argv[4]);
            input >> launches;
        }
        {
            std::ofstream output(argv[4], std::ios::trunc);
            output << launches + 1;
        }
        const auto duration = std::chrono::milliseconds(std::stoi(argv[3]));
        if (argc == 5)
            std::this_thread::sleep_for(duration);
        else
        {
            const auto readinessDelay =
                std::chrono::milliseconds(std::stoi(argv[6]));
            const auto heartbeatInterval =
                std::chrono::milliseconds(std::stoi(argv[7]));
            const auto heartbeatDuration =
                std::chrono::milliseconds(std::stoi(argv[8]));
            const auto started = std::chrono::steady_clock::now();
            auto lastSignal = started;
            bool signalled = false;
            while (std::chrono::steady_clock::now() - started < duration)
            {
                const auto now = std::chrono::steady_clock::now();
                const auto elapsed = now - started;
                const bool withinHeartbeatWindow =
                    !signalled || heartbeatDuration.count() > 0 &&
                    elapsed <= readinessDelay + heartbeatDuration;
                if (readinessDelay.count() >= 0 &&
                    elapsed >= readinessDelay && withinHeartbeatWindow &&
                    (!signalled || heartbeatInterval.count() > 0 &&
                     now - lastSignal >= heartbeatInterval))
                {
                    writeSignal(argv[5],
                        std::chrono::duration_cast<std::chrono::microseconds>(
                            now.time_since_epoch()).count());
                    signalled = true;
                    lastSignal = now;
                }
                std::this_thread::sleep_for(5ms);
            }
        }
        return std::stoi(argv[2]);
    }

    try
    {
        require(argc >= 1, "test executable path is unavailable");
        Poco::Path executable(argv[0]);
        executable.makeAbsolute();
        TemporaryWorkspace workspace;
        Poco::Path worker(workspace.path);
        worker.append(executable.getFileName());
        Poco::File(executable).copyTo(worker.toString());
        Poco::Path processRoot(workspace.path);
        Poco::Path configuration(workspace.path);
        configuration.append("subprocess.properties");
        Poco::Path counter(workspace.path);
        counter.append("launch-count.txt");
        const auto counterPath = counter.toString();
        auto counterArgument = counterPath;
        std::replace(counterArgument.begin(), counterArgument.end(), '\\', '/');
        Poco::Path readiness(workspace.path);
        readiness.append("ready.signal");
        const auto readinessPath = readiness.toString();
        auto readinessArgument = readinessPath;
        std::replace(readinessArgument.begin(), readinessArgument.end(), '\\', '/');

        PocoDDS::ProcessManagement::SubprocessManagerOptions options;
        options.shutdownTimeoutMilliseconds = 250;
        SubprocessManager manager(Poco::Logger::get("SubprocessSupervisionSmoke"),
                                  options);

        resetCounter(counterPath);
        writeConfiguration(configuration.toString(), worker.getFileName(),
                           "on-failure", 2, 7, 25, counterArgument);
        require(manager.startFromConfiguration(configuration.toString(),
                                               processRoot.toString()) == 1,
                "initial recovery probe was not launched");
        const auto failed = waitFor(manager, [](const auto& process) {
            return process.state == "failed";
        });
        require(failed.state == "failed" && readCounter(counterPath) == 3 &&
                    manager.runningCount() == 0,
                "bounded on-failure recovery snapshot is incorrect");
        const auto failedInventory = manager.processes();
        require(failedInventory.size() == 1 &&
                    failedInventory.front().state == "failed",
                "process inventory did not expose exhausted recovery state");

        resetCounter(counterPath);
        writeConfiguration(configuration.toString(), worker.getFileName(),
                           "on-failure", 2, 0, 25, counterArgument);
        manager.startFromConfiguration(configuration.toString(),
                                       processRoot.toString());
        const auto cleanExit = waitFor(manager, [](const auto& process) {
            return process.state == "exited";
        });
        require(cleanExit.state == "exited" && readCounter(counterPath) == 1,
                "on-failure policy restarted a clean exit");

        resetCounter(counterPath);
        writeConfiguration(configuration.toString(), worker.getFileName(),
                           "always", 1, 0, 25, counterArgument);
        manager.startFromConfiguration(configuration.toString(),
                                       processRoot.toString());
        const auto always = waitFor(manager, [](const auto& process) {
            return process.state == "failed";
        });
        require(always.state == "failed" && readCounter(counterPath) == 2,
                "always policy did not consume exactly one restart attempt");

        resetCounter(counterPath);
        writeConfiguration(configuration.toString(), worker.getFileName(),
                           "always", 3, 0, 2000, counterArgument);
        manager.startFromConfiguration(configuration.toString(),
                                       processRoot.toString());
        require(manager.stop("recovery-probe"),
                "manual stop did not find the managed subprocess");
        std::this_thread::sleep_for(150ms);
        const auto stopped = manager.processes();
        require(stopped.size() == 1 && stopped.front().state == "stopped" &&
                    readCounter(counterPath) == 1 && manager.runningCount() == 0,
                "manual stop was incorrectly restarted by the supervisor");

        writeConfiguration(configuration.toString(), worker.getFileName(),
                           "invalid-policy", 1, 0, 25, counterArgument);
        bool invalidRejected = false;
        try
        {
            manager.startFromConfiguration(configuration.toString(),
                                           processRoot.toString());
        }
        catch (const Poco::InvalidArgumentException&)
        {
            invalidRejected = true;
        }
        require(invalidRejected, "invalid restart policy was accepted");

        resetCounter(counterPath);
        writeConfiguration(configuration.toString(), worker.getFileName(),
                           "never", 0, 0, 300, counterArgument,
                           "ready.signal", readinessArgument,
                           100, 0, 0, 500, 0);
        manager.startFromConfiguration(configuration.toString(),
                                       processRoot.toString());
        waitFor(manager, [](const auto& process) {
            return process.state == "starting";
        });
        waitFor(manager, [](const auto& process) {
            return process.state == "running";
        });
        const auto readinessExit = waitFor(manager, [](const auto& process) {
            return process.state == "exited";
        });
        require(readinessExit.state == "exited" &&
                    readCounter(counterPath) == 1,
                "fresh startup readiness did not gate running state");

        resetCounter(counterPath);
        writeConfiguration(configuration.toString(), worker.getFileName(),
                           "on-failure", 1, 0, 2000, counterArgument,
                           "ready.signal", readinessArgument,
                           -1, 0, 0, 100, 0);
        manager.startFromConfiguration(configuration.toString(),
                                       processRoot.toString());
        const auto missingReadiness = waitFor(manager, [](const auto& process) {
            return process.state == "failed";
        });
        require(missingReadiness.state == "failed" &&
                    readCounter(counterPath) == 2,
                "missing readiness did not exhaust the bounded restart budget");

        resetCounter(counterPath);
        writeConfiguration(configuration.toString(), worker.getFileName(),
                           "on-failure", 1, 0, 2000, counterArgument,
                           "ready.signal", readinessArgument,
                           20, 30, 120, 200, 100);
        manager.startFromConfiguration(configuration.toString(),
                                       processRoot.toString());
        waitFor(manager, [](const auto& process) {
            return process.state == "running";
        });
        const auto heartbeatLost = waitFor(manager, [](const auto& process) {
            return process.state == "failed";
        });
        require(heartbeatLost.state == "failed" &&
                    readCounter(counterPath) == 2,
                "heartbeat loss did not use the bounded recovery policy");

        writeConfiguration(configuration.toString(), worker.getFileName(),
                           "never", 0, 0, 25, counterArgument,
                           {}, {}, -1, 0, 0, 100, 0);
        bool missingFileRejected = false;
        try
        {
            manager.startFromConfiguration(configuration.toString(),
                                           processRoot.toString());
        }
        catch (const Poco::InvalidArgumentException&)
        {
            missingFileRejected = true;
        }
        require(missingFileRejected,
                "readiness timeout without readinessFile was accepted");

        manager.stopAll();
        std::cout << "SUBPROCESS_SUPERVISION_RECOVERY_PASS "
                     "boundedRestart=1 cleanExit=1 always=1 manualStop=1 "
                     "invalidPolicy=1 readinessGate=1 readinessTimeout=1 "
                     "heartbeatTimeout=1\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "Subprocess supervision smoke failed: "
                  << exception.what() << '\n';
        return 1;
    }
}
