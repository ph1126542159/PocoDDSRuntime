#include "PocoDDS/ProcessManagement/SubprocessManager.h"
#include "PocoDDS/ProcessManagement/ProcessDependencyGraph.h"
#include "PocoDDS/ProcessManagement/ProcessDesiredStateMaintenance.h"

#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/Logger.h>
#include <Poco/Path.h>
#include <Poco/Process.h>
#include <Poco/TemporaryFile.h>
#include <Poco/Util/ServerApplication.h>

#include <algorithm>
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace
{
using namespace std::chrono_literals;
using PocoDDS::ProcessManagement::SubprocessManager;

void require(bool condition, const std::string& message)
{
    if (!condition)
        throw std::runtime_error(message);
}

class DesiredStateChild final : public Poco::Util::ServerApplication
{
  protected:
    int main(const std::vector<std::string>& arguments) override
    {
        if ((arguments.size() != 2 && arguments.size() != 3) ||
            (arguments[0] != "--desired-state-child" &&
             arguments[0] != "--desired-state-exit"))
            return Application::EXIT_CONFIG;
        int launches = 0;
        {
            std::ifstream input(arguments[1]);
            input >> launches;
        }
        {
            std::ofstream output(arguments[1], std::ios::trunc);
            output << launches + 1;
            if (!output)
                return Application::EXIT_IOERR;
        }
        if (arguments[0] == "--desired-state-exit")
            return std::stoi(arguments[2]);
        waitForTerminationRequest();
        return Application::EXIT_OK;
    }
};

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

void writeCounter(const std::string& path, int value)
{
    std::ofstream output(path, std::ios::trunc);
    output << value;
    require(static_cast<bool>(output), "failed to write launch counter");
}

int readCounter(const std::string& path)
{
    for (int attempt = 0; attempt < 50; ++attempt)
    {
        std::ifstream input(path);
        int value = -1;
        if (input >> value)
            return value;
        std::this_thread::sleep_for(5ms);
    }
    throw std::runtime_error("failed to read launch counter");
}

void waitForCounter(const std::string& path, int expected)
{
    const auto deadline = std::chrono::steady_clock::now() + 5s;
    do
    {
        if (readCounter(path) == expected)
            return;
        std::this_thread::sleep_for(20ms);
    } while (std::chrono::steady_clock::now() < deadline);
    throw std::runtime_error("timed out waiting for launch counter " +
                             std::to_string(expected));
}

void writeConfiguration(const std::string& path,
                        const std::string& executable,
                        const std::string& counter,
                        const std::string& statePath)
{
    std::ofstream output(path, std::ios::trunc);
    output << "subprocess.count = 1\n"
           << "subprocess.supervisionIntervalMilliseconds = 20\n"
           << "subprocess.desiredStatePersistence.enabled = true\n"
           << "subprocess.desiredStatePersistence.path = " << statePath << "\n"
           << "subprocess.desiredStatePersistence.scrubIntervalMilliseconds = 50\n"
           << "subprocess.0.enabled = true\n"
           << "subprocess.0.name = durable-worker\n"
           << "subprocess.0.location = local\n"
           << "subprocess.0.required = true\n"
           << "subprocess.0.dependency.count = 0\n"
           << "subprocess.0.path = " << executable << "\n"
           << "subprocess.0.workingDirectory = .\n"
           << "subprocess.0.restartPolicy = never\n"
           << "subprocess.0.argument.count = 2\n"
           << "subprocess.0.argument.0 = --desired-state-child\n"
           << "subprocess.0.argument.1 = " << counter << "\n";
    require(static_cast<bool>(output),
            "failed to write desired-state fixture");
}

void writeFailingConfiguration(const std::string& path,
                               const std::string& executable,
                               const std::string& counter)
{
    std::ofstream output(path, std::ios::trunc);
    output << "subprocess.count = 1\n"
           << "subprocess.supervisionIntervalMilliseconds = 20\n"
           << "subprocess.desiredStatePersistence.enabled = true\n"
           << "subprocess.desiredStatePersistence.path = state/crash.json\n"
           << "subprocess.0.enabled = true\n"
           << "subprocess.0.name = crash-worker\n"
           << "subprocess.0.location = local\n"
           << "subprocess.0.required = true\n"
           << "subprocess.0.dependency.count = 0\n"
           << "subprocess.0.path = " << executable << "\n"
           << "subprocess.0.workingDirectory = .\n"
           << "subprocess.0.restartPolicy = on-failure\n"
           << "subprocess.0.restartMaximumAttempts = 0\n"
           << "subprocess.0.argument.count = 3\n"
           << "subprocess.0.argument.0 = --desired-state-exit\n"
           << "subprocess.0.argument.1 = " << counter << "\n"
           << "subprocess.0.argument.2 = 7\n";
    require(static_cast<bool>(output),
            "failed to write crash-loop desired-state fixture");
}

void overwrite(const std::string& path, const std::string& content)
{
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    output << content;
    require(static_cast<bool>(output), "failed to corrupt desired-state file");
}

SubprocessManager makeManager()
{
    PocoDDS::ProcessManagement::SubprocessManagerOptions options;
    options.shutdownTimeoutMilliseconds = 1000;
    return SubprocessManager(Poco::Logger::get("SubprocessDesiredStateSmoke"),
                             options);
}

PocoDDS::ProcessManagement::ProcessDesiredStatePersistenceStatus
waitForPersistenceIntegrity(const std::string& expectedState)
{
    const auto deadline = std::chrono::steady_clock::now() + 5s;
    do
    {
        const auto status =
            PocoDDS::ProcessManagement::activeProcessDependencyGraph()
                .desiredStatePersistence;
        if (status.integrityState == expectedState)
            return status;
        std::this_thread::sleep_for(20ms);
    } while (std::chrono::steady_clock::now() < deadline);
    throw std::runtime_error(
        "timed out waiting for desired-state integrity " + expectedState);
}
} // namespace

int main(int argc, char** argv)
{
    if (argc > 1 &&
        (std::string(argv[1]) == "--desired-state-child" ||
         std::string(argv[1]) == "--desired-state-exit"))
    {
        DesiredStateChild child;
        return child.run(argc, argv);
    }
    if (argc == 4 &&
        std::string(argv[1]) == "--desired-state-contender")
    {
        try
        {
            auto manager = makeManager();
            manager.startFromConfiguration(argv[2], argv[3]);
            manager.stopAll();
            return 2;
        }
        catch (const Poco::FileAccessDeniedException&)
        {
            return 0;
        }
        catch (...)
        {
            return 3;
        }
    }

    try
    {
        require(argc >= 1, "test executable path is unavailable");
        const auto unavailable =
            PocoDDS::ProcessManagement::recommitActiveProcessDesiredState(0);
        require(!unavailable.accepted && !unavailable.changed &&
                    unavailable.code == "manager-unavailable",
                "desired-state recommit did not reject a missing manager");
        Poco::Path executable(argv[0]);
        executable.makeAbsolute();
        TemporaryWorkspace workspace;
        Poco::Path worker(workspace.path);
        worker.append(executable.getFileName());
        Poco::File(executable).copyTo(worker.toString());

        Poco::Path configuration(workspace.path);
        configuration.append("desired-state.properties");
        Poco::Path counter(workspace.path);
        counter.append("launch-count.txt");
        auto counterArgument = counter.toString();
        std::replace(counterArgument.begin(), counterArgument.end(), '\\', '/');
        writeCounter(counter.toString(), 0);
        writeConfiguration(configuration.toString(), worker.getFileName(),
                           counterArgument, "state/desired.json");

        {
            auto manager = makeManager();
            require(manager.startFromConfiguration(configuration.toString(),
                                                   workspace.path.toString()) == 1,
                    "initial desired process was not launched");
            waitForCounter(counter.toString(), 1);
            const auto persistence =
                PocoDDS::ProcessManagement::activeProcessDependencyGraph()
                    .desiredStatePersistence;
            require(persistence.enabled && persistence.healthy &&
                        persistence.leaseHeld &&
                        !persistence.recoveredFromPrevious &&
                        persistence.primaryValid &&
                        !persistence.previousAvailable &&
                        !persistence.previousValid &&
                        persistence.generation == 1 &&
                        persistence.lastIntegrityCheckEpochMicroseconds > 0 &&
                        persistence.state == "healthy" &&
                        persistence.integrityState == "healthy",
                    "desired-state persistence status is not observable");

            Poco::Process::Args contenderArguments{
                "--desired-state-contender", configuration.toString(),
                workspace.path.toString()};
            Poco::ProcessHandle contender = Poco::Process::launch(
                executable.toString(), contenderArguments,
                workspace.path.toString());
            require(contender.wait() == 0 &&
                        readCounter(counter.toString()) == 1,
                    "a second process acquired the desired-state writer lease");
            require(manager.stop("durable-worker"),
                    "manual stop was rejected");
            const auto stoppedPersistence =
                PocoDDS::ProcessManagement::activeProcessDependencyGraph()
                    .desiredStatePersistence;
            require(manager.runningCount() == 0 &&
                        manager.processes().front().state == "stopped" &&
                        stoppedPersistence.enabled &&
                        stoppedPersistence.healthy &&
                        stoppedPersistence.leaseHeld &&
                        stoppedPersistence.primaryValid &&
                        stoppedPersistence.previousAvailable &&
                        stoppedPersistence.previousValid &&
                        stoppedPersistence.generation == 2,
                    "manual stop did not reach stopped state");
        }

        {
            auto manager = makeManager();
            require(manager.startFromConfiguration(configuration.toString(),
                                                   workspace.path.toString()) == 0,
                    "stopped intent was lost across manager restart");
            std::this_thread::sleep_for(100ms);
            require(readCounter(counter.toString()) == 1 &&
                        manager.processes().front().state == "stopped",
                    "persisted stopped process was relaunched");
            require(manager.start("durable-worker"),
                    "manual start was rejected");
            waitForCounter(counter.toString(), 2);
        }

        {
            auto manager = makeManager();
            require(manager.startFromConfiguration(configuration.toString(),
                                                   workspace.path.toString()) == 1,
                    "running intent was lost across manager restart");
            waitForCounter(counter.toString(), 3);
        }

        Poco::Path state(workspace.path);
        state.append("state/desired.json");
        overwrite(state.toString(), "{corrupt-primary");
        {
            auto manager = makeManager();
            require(manager.startFromConfiguration(configuration.toString(),
                                                   workspace.path.toString()) == 0,
                    "invalid primary did not recover the previous stopped intent");
            require(manager.processes().front().state == "stopped" &&
                        readCounter(counter.toString()) == 3,
                    "recovery snapshot did not remain fail-closed");
        }

        overwrite(state.toString(), "{corrupt-primary-again");
        overwrite(state.toString() + ".previous", "{corrupt-previous");
        bool corruptionRejected = false;
        try
        {
            auto manager = makeManager();
            manager.startFromConfiguration(configuration.toString(),
                                           workspace.path.toString());
        }
        catch (const Poco::DataFormatException&)
        {
            corruptionRejected = true;
        }
        require(corruptionRejected && readCounter(counter.toString()) == 3,
                "unrecoverable desired-state corruption was not fail-closed");

        Poco::Path transactionalConfiguration(workspace.path);
        transactionalConfiguration.append("transactional.properties");
        writeConfiguration(transactionalConfiguration.toString(),
                           worker.getFileName(), counterArgument,
                           "state/transactional.json");
        {
            auto manager = makeManager();
            require(manager.startFromConfiguration(
                        transactionalConfiguration.toString(),
                        workspace.path.toString()) == 1,
                    "transactional fixture did not launch");
            waitForCounter(counter.toString(), 4);
            require(manager.stop("durable-worker"),
                    "transactional fixture stop was rejected");
            Poco::Path transactionalState(workspace.path);
            transactionalState.append("state/transactional.json");
            Poco::File(transactionalState).remove();
            Poco::File(transactionalState).createDirectory();
            bool writeFailureRejected = false;
            try
            {
                manager.start("durable-worker");
            }
            catch (const Poco::Exception&)
            {
                writeFailureRejected = true;
            }
            require(writeFailureRejected && manager.runningCount() == 0 &&
                        manager.processes().front().state == "stopped" &&
                        readCounter(counter.toString()) == 4,
                    "failed desired-state write executed a lifecycle action");
        }

        Poco::Path crashConfiguration(workspace.path);
        crashConfiguration.append("crash-loop.properties");
        writeFailingConfiguration(crashConfiguration.toString(),
                                  worker.getFileName(), counterArgument);
        {
            auto manager = makeManager();
            require(manager.startFromConfiguration(
                        crashConfiguration.toString(),
                        workspace.path.toString()) == 1,
                    "crash-loop fixture did not launch");
            waitForCounter(counter.toString(), 5);
            const auto deadline = std::chrono::steady_clock::now() + 5s;
            while (manager.processes().front().state != "failed" &&
                   std::chrono::steady_clock::now() < deadline)
                std::this_thread::sleep_for(20ms);
            require(manager.processes().front().state == "failed",
                    "crash-loop fixture did not exhaust its zero retry budget");
        }
        {
            auto manager = makeManager();
            require(manager.startFromConfiguration(
                        crashConfiguration.toString(),
                        workspace.path.toString()) == 0,
                    "Runtime restart bypassed the exhausted crash-loop budget");
            std::this_thread::sleep_for(100ms);
            require(readCounter(counter.toString()) == 5 &&
                        manager.processes().front().state == "stopped",
                    "persisted terminal authorization relaunched a crash loop");
        }

        Poco::Path scrubConfiguration(workspace.path);
        scrubConfiguration.append("online-scrub.properties");
        writeConfiguration(scrubConfiguration.toString(),
                           worker.getFileName(), counterArgument,
                           "state/online-scrub.json");
        {
            auto manager = makeManager();
            require(manager.startFromConfiguration(
                        scrubConfiguration.toString(),
                        workspace.path.toString()) == 1,
                    "online scrub fixture did not launch");
            waitForCounter(counter.toString(), 6);
            Poco::Path scrubState(workspace.path);
            scrubState.append("state/online-scrub.json");
            overwrite(scrubState.toString(), "{online-corruption");
            const auto degraded =
                waitForPersistenceIntegrity("primary-invalid");
            const auto processIdBeforeRepair =
                manager.processes().front().processId;
            require(!degraded.healthy && !degraded.primaryValid &&
                        degraded.lastIntegrityCheckEpochMicroseconds > 0 &&
                        manager.runningCount() == 1,
                    "online scrub did not publish primary corruption without disrupting the child");
            const auto repaired =
                PocoDDS::ProcessManagement::recommitActiveProcessDesiredState(
                    degraded.generation);
            const auto processAfterRepair = manager.processes().front();
            require(repaired.accepted && repaired.changed &&
                        repaired.code == "recommitted" &&
                        repaired.previousGeneration == degraded.generation &&
                        repaired.generation == degraded.generation + 1 &&
                        repaired.healthy &&
                        repaired.integrityState == "healthy" &&
                        processAfterRepair.processId == processIdBeforeRepair &&
                        processAfterRepair.state == "running" &&
                        manager.runningCount() == 1 &&
                        readCounter(counter.toString()) == 6,
                    "CAS recommit changed process lifecycle state");
            const auto stale =
                PocoDDS::ProcessManagement::recommitActiveProcessDesiredState(
                    degraded.generation);
            require(!stale.accepted && !stale.changed &&
                        stale.code == "generation-conflict" &&
                        stale.generation == repaired.generation &&
                        manager.processes().front().processId ==
                            processIdBeforeRepair,
                    "stale desired-state generation bypassed CAS");
            const auto noOp =
                PocoDDS::ProcessManagement::recommitActiveProcessDesiredState(
                    repaired.generation);
            require(noOp.accepted && !noOp.changed &&
                        noOp.code == "already-healthy" &&
                        noOp.generation == repaired.generation,
                    "healthy desired-state recommit was not idempotent");
            require(manager.stop("durable-worker"),
                    "online scrub cleanup stop was rejected");
            const auto finalStatus = waitForPersistenceIntegrity("healthy");
            require(finalStatus.healthy && finalStatus.primaryValid &&
                        finalStatus.generation == 3 &&
                        manager.runningCount() == 0,
                    "online scrub cleanup did not persist the stopped state");
        }

        Poco::Path escapingConfiguration(workspace.path);
        escapingConfiguration.append("escaping.properties");
        writeConfiguration(escapingConfiguration.toString(),
                           worker.getFileName(), counterArgument,
                           "../escaped-desired-state.json");
        bool escapeRejected = false;
        try
        {
            auto manager = makeManager();
            manager.startFromConfiguration(escapingConfiguration.toString(),
                                           workspace.path.toString());
        }
        catch (const Poco::InvalidArgumentException&)
        {
            escapeRejected = true;
        }
        require(escapeRejected && readCounter(counter.toString()) == 6,
                "desired-state path escaped the Runtime process root");

        Poco::Path disabledConfiguration(workspace.path);
        disabledConfiguration.append("persistence-disabled.properties");
        overwrite(disabledConfiguration.toString(), "subprocess.count = 0\n");
        {
            auto manager = makeManager();
            require(manager.startFromConfiguration(
                        disabledConfiguration.toString(),
                        workspace.path.toString()) == 0,
                    "disabled persistence fixture failed to initialize");
            const auto disabled =
                PocoDDS::ProcessManagement::recommitActiveProcessDesiredState(0);
            require(!disabled.accepted && !disabled.changed &&
                        disabled.code == "persistence-disabled" &&
                        disabled.generation == 0,
                    "desired-state recommit did not reject disabled persistence");
        }

        std::cout << "SUBPROCESS_DESIRED_STATE_PASS stoppedAcrossRestart=1 "
                     "runningAcrossRestart=1 previousRecovery=1 "
                     "corruptionFailClosed=1 transactionalMutation=1 "
                     "crashLoopDurable=1 rootConfined=1 "
                     "leaseExclusive=1 statusObservable=1 "
                     "onlineScrub=1 scrubRepair=1 "
                     "casRecommit=1 staleGeneration=1 "
                     "zeroLifecycleEffect=1 managerUnavailable=1 "
                     "disabledRejected=1\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "Subprocess desired-state smoke failed: "
                  << exception.what() << '\n';
        return 1;
    }
}
