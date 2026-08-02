#include "Poco/File.h"
#include "Poco/Path.h"
#include "Poco/Process.h"

#include <algorithm>
#include <chrono>
#include <fstream>
#include <iostream>
#include <thread>

int main(int argc, char** argv)
{
    if (argc != 4) return 64;
    Poco::Path state(argv[3]); state.append("launcher-heartbeat-state.txt");
    Poco::Path heartbeat(argv[3]); heartbeat.append("launcher-required-heartbeat.txt");
    Poco::Path config(argv[3]); config.append("launcher-heartbeat-test.properties");
    for (const auto& path : {state, heartbeat, config})
        if (Poco::File(path).exists()) Poco::File(path).remove(false);
    std::string heartbeatText = heartbeat.toString();
    std::replace(heartbeatText.begin(), heartbeatText.end(), '\\', '/');
    {
        std::ofstream output(config.toString(), std::ios::trunc);
        output << "relaunchDelay = 20\nrestartBudget.maxRestarts = 2\n"
               << "restartBudget.windowMilliseconds = 10000\nwatchdog.file = "
               << heartbeatText
               << "\nwatchdog.timeout = 100\nwatchdog.interval = 20\n"
               << "watchdog.startupGraceMilliseconds = 100\nwatchdog.requireFile = true\n"
               << "osp.bundleMonitor.enabled = false\nlogging.loggers.root.channel = console\n"
               << "logging.loggers.root.level = information\n"
               << "logging.channels.console.class = ConsoleChannel\n";
    }
#if defined(_WIN32)
    const std::string configOption = "/config-file=" + config.toString();
#else
    const std::string configOption = "--config-file=" + config.toString();
#endif
    Poco::Process::Args arguments{configOption, argv[2], state.toString()};
    Poco::ProcessHandle launcher = Poco::Process::launch(argv[1], arguments);
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(8);
    while (Poco::Process::isRunning(launcher) && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
    if (Poco::Process::isRunning(launcher)) { Poco::Process::kill(launcher); return 2; }
    const int exitCode = launcher.wait();
    int launches = 0; { std::ifstream input(state.toString()); input >> launches; }
    for (const auto& path : {state, heartbeat, config})
        if (Poco::File(path).exists()) Poco::File(path).remove(false);
    if (exitCode == 0 || launches != 3) return 1;
    std::cout << "LAUNCHER_MISSING_HEARTBEAT_PASS launches=" << launches << '\n';
    return 0;
}
