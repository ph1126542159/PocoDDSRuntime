#include <chrono>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <string>
#include <thread>

namespace
{
std::string readEnvironment(const char* name)
{
#if defined(_WIN32)
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, name) != 0)
        return {};
    const std::unique_ptr<char, decltype(&std::free)> holder(value, &std::free);
    return size > 0 ? std::string(value) : std::string{};
#else
    if (const char* value = std::getenv(name)) return value;
    return {};
#endif
}
}

int main(int argc, char** argv)
{
    if (argc != 2)
        return 64;
    {
        std::ofstream output(argv[1], std::ios::trunc);
        if (!output)
            return 65;
        output << "launched\nprofile=" << readEnvironment("PDR_FASTDDS_PROFILE")
               << "\nsha256=" << readEnvironment("PDR_FASTDDS_PROFILE_SHA256") << '\n';
    }
    std::this_thread::sleep_for(std::chrono::seconds(10));
    return 0;
}
