#include "PocoDDS/DDS/Runtime.h"

#include <algorithm>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <string>

namespace
{
constexpr const char* profileEnvironment = "PDR_FASTDDS_PROFILE";
constexpr const char* profileSha256Environment = "PDR_FASTDDS_PROFILE_SHA256";
constexpr const char* participantName = "pdr-fastdds-profile-check";

void printUsage(std::ostream& output)
{
    output << "Usage: pdr-fastdds-profile-check [--profile <path> "
              "[--sha256 <lowercase-digest>]]\n"
              "Validates PDR_FASTDDS_PROFILE when --profile is omitted.\n";
}

void setEnvironment(const char* name, const std::string& value)
{
#if defined(_WIN32)
    if (_putenv_s(name, value.c_str()) != 0)
        throw std::runtime_error("cannot set Fast DDS profile environment");
#else
    if (setenv(name, value.c_str(), 1) != 0)
        throw std::runtime_error("cannot set Fast DDS profile environment");
#endif
}

void clearEnvironment(const char* name)
{
#if defined(_WIN32)
    if (_putenv_s(name, "") != 0)
        throw std::runtime_error("cannot clear Fast DDS profile environment");
#else
    if (unsetenv(name) != 0)
        throw std::runtime_error("cannot clear Fast DDS profile environment");
#endif
}
} // namespace

int main(int argc, char** argv)
{
    try
    {
        if (argc == 2 && std::string(argv[1]) == "--help")
        {
            printUsage(std::cout);
            return 0;
        }
        if (argc != 1 && argc != 3 && argc != 5)
        {
            printUsage(std::cerr);
            return 2;
        }
        if (argc == 3 || argc == 5)
        {
            if (std::string(argv[1]) != "--profile" || std::string(argv[2]).empty())
            {
                printUsage(std::cerr);
                return 2;
            }
            setEnvironment(profileEnvironment, argv[2]);
            if (argc == 3) clearEnvironment(profileSha256Environment);
            if (argc == 5)
            {
                if (std::string(argv[3]) != "--sha256" || std::string(argv[4]).empty())
                {
                    printUsage(std::cerr);
                    return 2;
                }
                setEnvironment(profileSha256Environment, argv[4]);
            }
        }

        PocoDDS::FastDDS::Runtime runtime(0, participantName);
        const auto snapshots = PocoDDS::FastDDS::Runtime::snapshots();
        const auto snapshot = std::find_if(
            snapshots.begin(), snapshots.end(),
            [](const auto& item) { return item.participantName == participantName; });
        if (snapshot == snapshots.end())
            throw std::runtime_error("validation Runtime snapshot is unavailable");

        const bool configured = snapshot->qosProfile != "Fast DDS defaults";
        std::cout << "PDR_FASTDDS_PROFILE_CHECK_PASS configured="
                  << (configured ? "true" : "false")
                  << " transport=" << snapshot->transport
                  << " summary=" << snapshot->qosProfile << '\n';
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "PDR_FASTDDS_PROFILE_CHECK_ERROR: " << error.what() << '\n';
        return 1;
    }
}
