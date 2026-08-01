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
int launchCount(const std::string& path)
{
    std::ifstream input(path);
    int count = 0;
    input >> count;
    return count;
}
}

int main(int argc, char** argv)
{
    if (argc != 4)
        return 64;
    const std::string launcher = argv[1];
    const std::string child = argv[2];
    Poco::Path statePath(argv[3]);
    statePath.append("launcher-crash-recovery-state.txt");
    Poco::File stateFile(statePath);
    if (stateFile.exists())
        stateFile.remove(false);

#if defined(_WIN32)
    const std::string configOption = std::string("/config-file=") + PDR_LAUNCHER_TEST_CONFIG;
#else
    const std::string configOption = std::string("--config-file=") + PDR_LAUNCHER_TEST_CONFIG;
#endif
    Poco::Process::Args arguments{configOption, child, statePath.toString()};
    Poco::ProcessHandle handle = Poco::Process::launch(launcher, arguments);
    bool relaunched = false;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(8);
    while (std::chrono::steady_clock::now() < deadline)
    {
        if (launchCount(statePath.toString()) >= 2)
        {
            relaunched = true;
            break;
        }
        if (!Poco::Process::isRunning(handle))
            break;
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    if (Poco::Process::isRunning(handle))
    {
        try
        {
            Poco::Process::requestTermination(handle.id());
            const auto stopDeadline =
                std::chrono::steady_clock::now() + std::chrono::seconds(3);
            while (Poco::Process::isRunning(handle) &&
                   std::chrono::steady_clock::now() < stopDeadline)
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
            if (Poco::Process::isRunning(handle))
                Poco::Process::kill(handle);
        }
        catch (const Poco::Exception&)
        {
            if (Poco::Process::isRunning(handle))
                Poco::Process::kill(handle);
        }
    }
    if (stateFile.exists())
        stateFile.remove(false);
    if (!relaunched)
        return 1;
    std::cout << "LAUNCHER_CRASH_RECOVERY_PASS launches=2\n";
    return 0;
}
