#include "Poco/File.h"
#include "Poco/Path.h"
#include "Poco/Process.h"

#include <algorithm>
#include <chrono>
#include <fstream>
#include <string>
#include <thread>

int main(int argc, char** argv)
{
    if (argc != 4) return 64;
    Poco::Path state(argv[3]); state.append("launcher-job-limit-state.txt");
    Poco::Path config(argv[3]); config.append("launcher-job-limit.properties");
    for (const auto& path : {state, config})
        if (Poco::File(path).exists()) Poco::File(path).remove(false);
    std::string stateText = state.toString();
    std::replace(stateText.begin(), stateText.end(), '\\', '/');
    {
        std::ofstream output(config.toString(), std::ios::trunc);
        output << "relaunchDelay = 1000\nrestartBudget.maxRestarts = 1\n"
               << "restartBudget.windowMilliseconds = 10000\nwatchdog.file =\n"
               << "watchdog.timeout = 1000\nwatchdog.interval = 100\n"
               << "resourceLimits.killProcessTreeOnExit = true\n"
               << "resourceLimits.activeProcessLimit = 1\n"
               << "resourceLimits.memoryBytes = 0\nresourceLimits.cpuRatePercent = 0\n"
               << "childArgument.count = 1\nchildArgument.0 = " << stateText << "\n"
               << "osp.bundleMonitor.enabled = false\nlogging.loggers.root.channel = console\n"
               << "logging.loggers.root.level = critical\n"
               << "logging.channels.console.class = ConsoleChannel\n";
    }
#if defined(_WIN32)
    const std::string configOption = "/config-file=" + config.toString();
#else
    const std::string configOption = "--config-file=" + config.toString();
#endif
    Poco::ProcessHandle launcher = Poco::Process::launch(argv[1], {configOption, argv[2]});
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!Poco::File(state).exists() && Poco::Process::isRunning(launcher) &&
           std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
    std::string result;
    if (Poco::File(state).exists()) { std::ifstream input(state.toString()); input >> result; }
    if (Poco::Process::isRunning(launcher))
    {
        Poco::Process::requestTermination(launcher.id());
        const auto stop = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (Poco::Process::isRunning(launcher) && std::chrono::steady_clock::now() < stop)
            std::this_thread::sleep_for(std::chrono::milliseconds(25));
        if (Poco::Process::isRunning(launcher)) Poco::Process::kill(launcher);
    }
    for (const auto& path : {state, config})
        if (Poco::File(path).exists()) Poco::File(path).remove(false);
    return result == "blocked" ? 0 : 1;
}
