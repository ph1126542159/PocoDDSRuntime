#include "Poco/Exception.h"
#include "Poco/Process.h"

#include <chrono>
#include <fstream>
#include <string>
#include <thread>

int main(int argc, char** argv)
{
    if (argc == 2 && std::string(argv[1]) == "--grandchild")
    {
        std::this_thread::sleep_for(std::chrono::seconds(10));
        return 0;
    }
    if (argc != 2) return 64;
    bool blocked = false;
    try
    {
        Poco::ProcessHandle child = Poco::Process::launch(argv[0], {"--grandchild"});
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        blocked = !Poco::Process::isRunning(child);
        if (!blocked) Poco::Process::kill(child);
    }
    catch (const Poco::Exception&)
    {
        blocked = true;
    }
    std::ofstream(argv[1], std::ios::trunc) << (blocked ? "blocked\n" : "allowed\n");
    std::this_thread::sleep_for(std::chrono::seconds(10));
    return blocked ? 0 : 1;
}
