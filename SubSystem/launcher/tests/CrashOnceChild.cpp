#include <chrono>
#include <fstream>
#include <string>
#include <thread>

int main(int argc, char** argv)
{
    if (argc != 2)
        return 64;
    const std::string statePath = argv[1];
    int launches = 0;
    {
        std::ifstream input(statePath);
        input >> launches;
    }
    ++launches;
    {
        std::ofstream output(statePath, std::ios::trunc);
        output << launches << '\n';
    }
    if (launches == 1)
        return 17;
    std::this_thread::sleep_for(std::chrono::seconds(30));
    return 0;
}
