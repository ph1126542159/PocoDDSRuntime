#include <fstream>
#include <string>

int main(int argc, char** argv)
{
    if (argc != 2) return 64;
    int launches = 0;
    { std::ifstream input(argv[1]); input >> launches; }
    { std::ofstream output(argv[1], std::ios::trunc); output << ++launches << '\n'; }
    return 17;
}
