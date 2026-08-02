#include <fstream>
#include <string>
#include <thread>
#include <chrono>

int main(int argc, char** argv)
{
    if (argc != 2) return 64;
    int launches = 0;
    { std::ifstream input(argv[1]); input >> launches; }
    { std::ofstream output(argv[1], std::ios::trunc); output << ++launches << '\n'; }
    std::this_thread::sleep_for(std::chrono::seconds(30));
    return 0;
}
