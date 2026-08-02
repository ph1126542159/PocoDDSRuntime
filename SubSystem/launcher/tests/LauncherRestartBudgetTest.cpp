#include "Poco/File.h"
#include "Poco/Path.h"
#include "Poco/Process.h"

#include <chrono>
#include <fstream>
#include <iostream>
#include <thread>

int main(int argc, char** argv)
{
    if (argc != 4) return 64;
    Poco::Path statePath(argv[3]);
    statePath.append("launcher-restart-budget-state.txt");
    Poco::File stateFile(statePath);
    if (stateFile.exists()) stateFile.remove(false);
#if defined(_WIN32)
    const std::string configOption = std::string("/config-file=") + PDR_LAUNCHER_BUDGET_CONFIG;
#else
    const std::string configOption = std::string("--config-file=") + PDR_LAUNCHER_BUDGET_CONFIG;
#endif
    Poco::Process::Args arguments{configOption, argv[2], statePath.toString()};
    Poco::ProcessHandle launcher = Poco::Process::launch(argv[1], arguments);
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(8);
    while (Poco::Process::isRunning(launcher) && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    if (Poco::Process::isRunning(launcher))
    {
        Poco::Process::kill(launcher);
        return 2;
    }
    const int exitCode = launcher.wait();
    int launches = 0;
    { std::ifstream input(statePath.toString()); input >> launches; }
    if (stateFile.exists()) stateFile.remove(false);
    if (exitCode == 0 || launches != 3) return 1;
    std::cout << "LAUNCHER_RESTART_BUDGET_PASS launches=" << launches
              << " exit=" << exitCode << '\n';
    return 0;
}
