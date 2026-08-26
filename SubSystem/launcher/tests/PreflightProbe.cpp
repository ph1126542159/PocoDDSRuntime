#include "Poco/Process.h"

#include <chrono>
#include <fstream>
#include <string>
#include <thread>

int main(int argc, char** argv)
{
    if (argc != 3)
        return 64;
    const std::string mode = argv[1];
    {
        std::ofstream output(argv[2], std::ios::app);
        if (!output)
            return 65;
        output << mode << ' ' << Poco::Process::id() << '\n';
    }
    if (mode == "pass")
        return 0;
    if (mode == "fail")
        return 23;
    if (mode == "hang")
    {
        std::this_thread::sleep_for(std::chrono::seconds(5));
        return 0;
    }
    return 64;
}
