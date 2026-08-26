#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/Path.h"
#include "Poco/Process.h"
#include "Poco/Timestamp.h"
#include "PocoDDS/BundleManagement/BundleRepositoryFingerprint.h"

#include <algorithm>
#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>

namespace
{
Poco::Path child(const Poco::Path& directory, const std::string& name)
{
    Poco::Path result(directory);
    result.makeDirectory();
    result.setFileName(name);
    return result;
}

void write(const Poco::Path& path, const std::string& value)
{
    Poco::File(path.parent()).createDirectories();
    Poco::FileOutputStream output(path.toString(), std::ios::out | std::ios::trunc);
    output << value;
}

std::string read(const Poco::Path& path)
{
    if (!Poco::File(path).exists()) return {};
    Poco::FileInputStream input(path.toString());
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

std::string portable(std::string value)
{
    std::replace(value.begin(), value.end(), '\\', '/');
    return value;
}

bool waitFor(const Poco::Path& deployment, const std::string& expected,
             const Poco::Path& count, int expectedCount,
             const Poco::ProcessHandle& launcher)
{
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(8);
    while (std::chrono::steady_clock::now() < deadline)
    {
        int launches = 0;
        { std::ifstream input(count.toString()); input >> launches; }
        if (read(deployment).find("state=" + expected) != std::string::npos &&
            launches >= expectedCount)
            return true;
        if (!Poco::Process::isRunning(launcher)) return false;
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    return false;
}

void stop(Poco::ProcessHandle& launcher)
{
    if (!Poco::Process::isRunning(launcher)) return;
    try { Poco::Process::requestTermination(launcher.id()); }
    catch (const Poco::Exception&) {}
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (Poco::Process::isRunning(launcher) && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    if (Poco::Process::isRunning(launcher))
    {
        // The handle overload closes its Windows process handle immediately,
        // which prevents the fixture from proving that termination completed.
        // Kill by PID, retain the original handle, and reap it explicitly.
        Poco::Process::kill(launcher.id());
        deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (Poco::Process::isRunning(launcher) &&
               std::chrono::steady_clock::now() < deadline)
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    if (Poco::Process::isRunning(launcher))
        throw Poco::SystemException("Launcher deployment fixture could not stop Launcher");
    launcher.wait();
}

bool scenario(const std::string& launcherPath, const std::string& childPath,
              const Poco::Path& root, const std::string& mode)
{
    Poco::Path repository(root); repository.pushDirectory(mode + "-bundles"); repository.makeDirectory();
    Poco::Path state(root); state.pushDirectory(mode + "-state"); state.makeDirectory();
    Poco::Path lkg(state); lkg.pushDirectory("last-known-good"); lkg.makeDirectory();
    Poco::File(repository).createDirectories();
    Poco::File(state).createDirectories();
    Poco::File(lkg).createDirectories();
    write(child(repository, "bundle.bndl"), "candidate");
    write(child(lkg, "bundle.bndl"), "stable");
    const std::string id = "tx-" + mode;
    const std::string candidateDigest =
        PocoDDS::BundleManagement::BundleRepositoryFingerprint::calculateDirectory(
            repository.toString());
    const Poco::Path transaction = child(state, "transaction.properties");
    const Poco::Path deployment = child(state, "deployment.properties");
    const Poco::Path count = child(root, mode + "-count.txt");
    write(transaction, "transactionId=" + id +
          "\nstate=restartRequired\nbundleCount=1\ncandidateDigest=" +
          candidateDigest + "\nerror=\n");
    if (mode == "tamper")
        write(child(repository, "bundle.bndl"), "candidate-changed-after-preflight");

    const Poco::Path config = child(root, mode + "-launcher.properties");
    write(config,
          "relaunchDelay=20\nrestartBudget.maxRestarts=1\n"
          "restartBudget.windowMilliseconds=60000\nwatchdog.file=\n"
          "watchdog.timeout=1000\nwatchdog.interval=50\n"
          "watchdog.startupGraceMilliseconds=1000\nwatchdog.requireFile=false\n"
          "resourceLimits.killProcessTreeOnExit=true\n"
          "resourceLimits.memoryBytes=0\nresourceLimits.activeProcessLimit=0\n"
          "resourceLimits.cpuRatePercent=0\nosp.bundleMonitor.enabled=false\n"
          "deployment.enabled=true\ndeployment.repository=" + portable(repository.toString()) +
          "\ndeployment.stateDirectory=" + portable(state.toString()) +
          "\ndeployment.pollMilliseconds=50\ndeployment.stopTimeoutMilliseconds=200\n"
          "deployment.startupTimeoutMilliseconds=1000\n"
          "deployment.probationMilliseconds=100\ndeployment.readiness.file=\n"
          "logging.loggers.root.channel=console\nlogging.channels.console.class=ConsoleChannel\n");

#if defined(_WIN32)
    const std::string configOption = "/config-file=" + config.toString();
#else
    const std::string configOption = "--config-file=" + config.toString();
#endif
    Poco::Process::Args arguments{configOption, childPath, transaction.toString(),
                                 count.toString(), id, mode, candidateDigest};
    Poco::ProcessHandle launcher = Poco::Process::launch(launcherPath, arguments);
    const bool observed = waitFor(deployment,
                                  mode == "commit" ? "committed" :
                                  mode == "rollback" ? "rolledBack" : "rejected",
                                  count, mode == "commit" ? 2 : mode == "rollback" ? 3 : 1,
                                  launcher);
    stop(launcher);
    if (!observed) return false;
    if (mode == "rollback" && read(child(repository, "bundle.bndl")) != "stable")
        return false;
    if (mode == "tamper")
    {
        int launches = 0;
        { std::ifstream input(count.toString()); input >> launches; }
        if (launches != 1 || read(child(repository, "bundle.bndl")) !=
                                 "candidate-changed-after-preflight")
            return false;
    }
    return true;
}
} // namespace

int main(int argc, char** argv)
{
    if (argc != 4) return 64;
    Poco::Path root(argv[3]);
    root.pushDirectory("launcher-deployment-" +
                       std::to_string(Poco::Timestamp().epochMicroseconds()));
    root.makeDirectory();
    Poco::File(root).createDirectories();
    const bool committed = scenario(argv[1], argv[2], root, "commit");
    const bool rolledBack = scenario(argv[1], argv[2], root, "rollback");
    const bool tamperRejected = scenario(argv[1], argv[2], root, "tamper");
    Poco::File(root).remove(true);
    if (!committed || !rolledBack || !tamperRejected)
        return !committed ? 1 : !rolledBack ? 2 : 3;
    std::cout << "LAUNCHER_BUNDLE_DEPLOYMENT_PASS commit=1 rollback=1 tamperRejected=1\n";
    return 0;
}
