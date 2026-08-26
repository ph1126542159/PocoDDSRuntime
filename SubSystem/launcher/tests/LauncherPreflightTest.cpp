#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/Path.h"
#include "Poco/Process.h"

#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>

namespace
{
std::string portable(std::string value)
{
    for (auto& character : value)
        if (character == '\\') character = '/';
    return value;
}

void removeIfPresent(const Poco::Path& path)
{
    Poco::File file(path);
    if (file.exists()) file.remove(false);
}

void writeConfig(const Poco::Path& path, const std::string& probe,
                 const std::string& mode, const Poco::Path& probeState,
                 const Poco::Path& childState, const Poco::Path& workingDirectory,
                 int timeoutMilliseconds)
{
    std::ofstream output(path.toString(), std::ios::trunc);
    output << "osp.bundleMonitor.enabled=false\n"
              "relaunchDelay=20\n"
              "restartBudget.maxRestarts=1\n"
              "restartBudget.windowMilliseconds=10000\n"
              "watchdog.file=\n"
              "childArgument.count=1\n"
              "childArgument.0=" << portable(childState.toString()) << "\n"
              "childWorkingDirectory=" << portable(workingDirectory.toString()) << "\n"
              "preflight.count=1\n"
              "preflight.0.name=test-" << mode << "\n"
              "preflight.0.executable=" << portable(probe) << "\n"
              "preflight.0.argument.count=2\n"
              "preflight.0.argument.0=" << mode << "\n"
              "preflight.0.argument.1=" << portable(probeState.toString()) << "\n"
              "preflight.0.workingDirectory=" << portable(workingDirectory.toString()) << "\n"
              "preflight.0.timeoutMilliseconds=" << timeoutMilliseconds << "\n";
}

void writeFastDdsConfig(const Poco::Path& path, const std::string& checker,
                        const Poco::Path& profile, const Poco::Path& childState,
                        const Poco::Path& workingDirectory,
                        const std::string& expectedSha256)
{
    std::ofstream output(path.toString(), std::ios::trunc);
    output << "osp.bundleMonitor.enabled=false\n"
              "relaunchDelay=20\n"
              "restartBudget.maxRestarts=1\n"
              "restartBudget.windowMilliseconds=10000\n"
              "watchdog.file=\n"
              "childArgument.count=1\n"
              "childArgument.0=" << portable(childState.toString()) << "\n"
              "childWorkingDirectory=" << portable(workingDirectory.toString()) << "\n"
              "childEnvironment.count=2\n"
              "childEnvironment.0.name=PDR_FASTDDS_PROFILE\n"
              "childEnvironment.0.value=" << portable(profile.toString()) << "\n"
              "childEnvironment.1.name=PDR_FASTDDS_PROFILE_SHA256\n"
              "childEnvironment.1.value=" << expectedSha256 << "\n"
              "preflight.count=1\n"
              "preflight.0.name=fastdds-profile\n"
              "preflight.0.executable=" << portable(checker) << "\n"
              "preflight.0.argument.count=0\n"
              "preflight.0.workingDirectory=" << portable(workingDirectory.toString()) << "\n"
              "preflight.0.timeoutMilliseconds=1000\n";
}

void writeDuplicateEnvironmentConfig(const Poco::Path& path,
                                     const Poco::Path& childState)
{
    std::ofstream output(path.toString(), std::ios::trunc);
    output << "osp.bundleMonitor.enabled=false\n"
              "childArgument.count=1\n"
              "childArgument.0=" << portable(childState.toString()) << "\n"
              "childEnvironment.count=2\n"
              "childEnvironment.0.name=PDR_DUPLICATE_TEST\n"
              "childEnvironment.0.value=first\n"
              "childEnvironment.1.name=PDR_DUPLICATE_TEST\n"
              "childEnvironment.1.value=second\n";
}

std::string configOption(const std::string& path)
{
#if defined(_WIN32)
    return "/config-file=" + path;
#else
    return "--config-file=" + path;
#endif
}

void stop(Poco::ProcessHandle& process)
{
    if (!Poco::Process::isRunning(process))
    {
        process.wait();
        return;
    }
    try { Poco::Process::requestTermination(process.id()); }
    catch (const Poco::Exception&) {}
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (Poco::Process::isRunning(process) && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
    if (Poco::Process::isRunning(process)) Poco::Process::kill(process);
    process.wait();
}

bool waitForFile(const Poco::Path& path, const Poco::ProcessHandle& launcher)
{
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(4);
    while (std::chrono::steady_clock::now() < deadline)
    {
        if (Poco::File(path).exists()) return true;
        if (!Poco::Process::isRunning(launcher)) return false;
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
    }
    return false;
}

int lineCount(const Poco::Path& path)
{
    std::ifstream input(path.toString());
    int count = 0;
    std::string line;
    while (std::getline(input, line)) ++count;
    return count;
}

bool contains(const Poco::Path& path, const std::string& expected)
{
    std::ifstream input(path.toString());
    const std::string content((std::istreambuf_iterator<char>(input)),
                              std::istreambuf_iterator<char>());
    return content.find(expected) != std::string::npos;
}

bool probeStopped(const Poco::Path& path)
{
    std::ifstream input(path.toString());
    std::string mode;
    Poco::Process::PID pid = 0;
    input >> mode >> pid;
    return input && pid != 0 && !Poco::Process::isRunning(pid);
}

bool rejectedScenario(const std::string& launcherPath, const std::string& childPath,
                      const Poco::Path& config, const Poco::Path& childState,
                      const Poco::Path& probeState)
{
    Poco::ProcessHandle launcher = Poco::Process::launch(
        launcherPath, {configOption(config.toString()), childPath});
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(4);
    while (Poco::Process::isRunning(launcher) && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
    if (Poco::Process::isRunning(launcher))
    {
        stop(launcher);
        return false;
    }
    const int result = launcher.wait();
    return result != 0 && !Poco::File(childState).exists() &&
           Poco::File(probeState).exists() && lineCount(probeState) == 1 &&
           probeStopped(probeState);
}

bool rejectedBeforeChild(const std::string& launcherPath, const std::string& childPath,
                         const Poco::Path& config, const Poco::Path& childState)
{
    Poco::ProcessHandle launcher = Poco::Process::launch(
        launcherPath, {configOption(config.toString()), childPath});
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(4);
    while (Poco::Process::isRunning(launcher) && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
    if (Poco::Process::isRunning(launcher))
    {
        stop(launcher);
        return false;
    }
    return launcher.wait() != 0 && !Poco::File(childState).exists();
}
} // namespace

int main(int argc, char** argv)
{
    if (argc != 8)
        return 64;
    Poco::Path workspace(argv[4]);
    workspace.makeAbsolute();
    const std::string suffix = std::to_string(Poco::Process::id());

    Poco::Path passConfig(workspace); passConfig.append("launcher-preflight-pass-" + suffix + ".properties");
    Poco::Path passProbe(workspace); passProbe.append("launcher-preflight-pass-probe-" + suffix + ".txt");
    Poco::Path passChild(workspace); passChild.append("launcher-preflight-pass-child-" + suffix + ".txt");
    writeConfig(passConfig, argv[2], "pass", passProbe, passChild, workspace, 1000);
    Poco::ProcessHandle passLauncher = Poco::Process::launch(
        argv[1], {configOption(passConfig.toString()), argv[3]});
    const bool passObserved = waitForFile(passChild, passLauncher);
    stop(passLauncher);
    const bool pass = passObserved && Poco::File(passProbe).exists() && lineCount(passProbe) == 1;

    Poco::Path failConfig(workspace); failConfig.append("launcher-preflight-fail-" + suffix + ".properties");
    Poco::Path failProbe(workspace); failProbe.append("launcher-preflight-fail-probe-" + suffix + ".txt");
    Poco::Path failChild(workspace); failChild.append("launcher-preflight-fail-child-" + suffix + ".txt");
    writeConfig(failConfig, argv[2], "fail", failProbe, failChild, workspace, 1000);
    const bool rejected = rejectedScenario(argv[1], argv[3], failConfig, failChild, failProbe);

    Poco::Path timeoutConfig(workspace); timeoutConfig.append("launcher-preflight-timeout-" + suffix + ".properties");
    Poco::Path timeoutProbe(workspace); timeoutProbe.append("launcher-preflight-timeout-probe-" + suffix + ".txt");
    Poco::Path timeoutChild(workspace); timeoutChild.append("launcher-preflight-timeout-child-" + suffix + ".txt");
    writeConfig(timeoutConfig, argv[2], "hang", timeoutProbe, timeoutChild, workspace, 100);
    const bool timedOut = rejectedScenario(
        argv[1], argv[3], timeoutConfig, timeoutChild, timeoutProbe);

    Poco::Path validFastDdsConfig(workspace);
    validFastDdsConfig.append("launcher-fastdds-valid-" + suffix + ".properties");
    Poco::Path validFastDdsChild(workspace);
    validFastDdsChild.append("launcher-fastdds-valid-child-" + suffix + ".txt");
    writeFastDdsConfig(
        validFastDdsConfig, argv[5], Poco::Path(argv[6]), validFastDdsChild,
        workspace, argv[7]);
    Poco::ProcessHandle validFastDdsLauncher = Poco::Process::launch(
        argv[1], {configOption(validFastDdsConfig.toString()), argv[3]});
    const bool validFastDds = waitForFile(validFastDdsChild, validFastDdsLauncher);
    stop(validFastDdsLauncher);
    const bool boundFastDds = validFastDds && contains(
        validFastDdsChild, "profile=" + portable(Poco::Path(argv[6]).toString())) &&
        contains(validFastDdsChild, "sha256=" + std::string(argv[7]));

    Poco::Path invalidFastDdsProfile(workspace);
    invalidFastDdsProfile.append("launcher-fastdds-invalid-" + suffix + ".properties");
    {
        std::ofstream output(invalidFastDdsProfile.toString(), std::ios::trunc);
        output << "profileVersion=1\navoidBuiltinMulticast=true\n";
    }
    Poco::Path invalidFastDdsConfig(workspace);
    invalidFastDdsConfig.append("launcher-fastdds-invalid-launcher-" + suffix + ".properties");
    Poco::Path invalidFastDdsChild(workspace);
    invalidFastDdsChild.append("launcher-fastdds-invalid-child-" + suffix + ".txt");
    writeFastDdsConfig(
        invalidFastDdsConfig, argv[5], invalidFastDdsProfile, invalidFastDdsChild,
        workspace, argv[7]);
    const bool invalidFastDds = rejectedBeforeChild(
        argv[1], argv[3], invalidFastDdsConfig, invalidFastDdsChild);

    Poco::Path duplicateEnvironmentConfig(workspace);
    duplicateEnvironmentConfig.append(
        "launcher-duplicate-environment-" + suffix + ".properties");
    Poco::Path duplicateEnvironmentChild(workspace);
    duplicateEnvironmentChild.append(
        "launcher-duplicate-environment-child-" + suffix + ".txt");
    writeDuplicateEnvironmentConfig(duplicateEnvironmentConfig, duplicateEnvironmentChild);
    const bool duplicateEnvironment = rejectedBeforeChild(
        argv[1], argv[3], duplicateEnvironmentConfig, duplicateEnvironmentChild);

    for (const auto& path : {passConfig, passProbe, passChild, failConfig, failProbe,
                             failChild, timeoutConfig, timeoutProbe, timeoutChild,
                             validFastDdsConfig, validFastDdsChild, invalidFastDdsProfile,
                             invalidFastDdsConfig, invalidFastDdsChild,
                             duplicateEnvironmentConfig, duplicateEnvironmentChild})
        removeIfPresent(path);

    if (!pass || !rejected || !timedOut || !boundFastDds || !invalidFastDds ||
        !duplicateEnvironment)
        return 1;
    std::cout << "LAUNCHER_PREFLIGHT_PASS pass=1 reject=1 timeout=1 fastdds=1 environment=1\n";
    return 0;
}
