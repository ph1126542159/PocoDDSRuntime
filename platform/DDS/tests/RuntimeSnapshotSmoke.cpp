#include "PocoDDS/DDS/Runtime.h"

#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>

namespace
{
constexpr const char* profileEnvironment = "PDR_FASTDDS_PROFILE";
constexpr const char* profileSha256Environment = "PDR_FASTDDS_PROFILE_SHA256";
constexpr const char* validProfileSha256 =
    "8c531f1d23a81712bc1baf5adcadace7eb6486e83be820e7d5ea064093b88871";

void setEnvironment(const char* name, const std::optional<std::string>& value)
{
#if defined(_WIN32)
    _putenv_s(name, value ? value->c_str() : "");
#else
    if (value)
        setenv(name, value->c_str(), 1);
    else
        unsetenv(name);
#endif
}

std::optional<std::string> readEnvironment(const char* name)
{
#if defined(_WIN32)
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, name) != 0)
        throw std::runtime_error("cannot read Fast DDS test environment");
    const std::unique_ptr<char, decltype(&std::free)> holder(value, &std::free);
    if (size == 0)
        return std::nullopt;
    return std::string(value);
#else
    if (const char* value = std::getenv(name))
        return std::string(value);
    return std::nullopt;
#endif
}

class EnvironmentGuard
{
public:
    EnvironmentGuard(const char* name, std::optional<std::string> value)
        : _name(name)
    {
        _previous = readEnvironment(_name);
        setEnvironment(_name, value);
    }

    ~EnvironmentGuard() { setEnvironment(_name, _previous); }

private:
    const char* _name;
    std::optional<std::string> _previous;
};

void writeProfile(const std::filesystem::path& path, const std::string& content)
{
    std::ofstream profile(path, std::ios::out | std::ios::trunc | std::ios::binary);
    if (!profile)
        throw std::runtime_error("cannot write Fast DDS test profile");
    profile << content;
}

bool rejectsProfile(const std::filesystem::path& path, const std::string& content,
                    const std::string& participant)
{
    writeProfile(path, content);
    try
    {
        PocoDDS::FastDDS::Runtime invalid(75, participant);
        return false;
    }
    catch (const std::invalid_argument&)
    {
        return true;
    }
}

bool rejectsCurrentProfile(const std::string& participant)
{
    try
    {
        PocoDDS::FastDDS::Runtime invalid(75, participant);
        return false;
    }
    catch (const std::invalid_argument&)
    {
        return true;
    }
}
} // namespace

int main()
{
    EnvironmentGuard isolatedProfile(profileEnvironment, std::nullopt);
    EnvironmentGuard isolatedDigest(profileSha256Environment, std::nullopt);
    const auto baseline = PocoDDS::FastDDS::Runtime::snapshots().size();
    {
        PocoDDS::FastDDS::Runtime runtime(73, "diagnostic-snapshot-smoke");
        const auto snapshots = PocoDDS::FastDDS::Runtime::snapshots();
        if (snapshots.size() != baseline + 1) return 1;
        const auto& snapshot = snapshots.back();
        if (snapshot.domainId != 73 || snapshot.participantName != "diagnostic-snapshot-smoke")
            return 2;
        if (snapshot.started || snapshot.topicCount || snapshot.writerCount || snapshot.readerCount)
            return 3;
        if (snapshot.transport != "UDPv4" || snapshot.qosProfile != "Fast DDS defaults")
            return 4;
    }
    const auto profilePath = std::filesystem::temp_directory_path() /
        ("pdr-fastdds-profile-" + std::to_string(
            std::chrono::steady_clock::now().time_since_epoch().count()) + ".properties");
    {
        const std::string validProfile =
            "profileVersion=1\n"
            "interfaceWhitelist=127.0.0.1\n"
            "initialPeers=127.0.0.1\n"
            "avoidBuiltinMulticast=true\n"
            "sharedMemory=true\n"
            "maxInitialPeersRange=4\n";
        writeProfile(profilePath, validProfile);
        EnvironmentGuard environment(profileEnvironment, profilePath.string());
        {
            EnvironmentGuard digest(profileSha256Environment, validProfileSha256);
            PocoDDS::FastDDS::Runtime runtime(74, "diagnostic-profile-snapshot");
            runtime.start();
            const auto snapshot = PocoDDS::FastDDS::Runtime::snapshots().back();
            if (snapshot.domainId != 74 || snapshot.transport != "UDPv4+SHM" ||
                snapshot.qosProfile !=
                    "deployment-file;discovery=initial-peers;interfaces=1;peers=1;range=4;integrity=sha256" ||
                !snapshot.started)
                return 5;
            runtime.stop();
        }
        writeProfile(profilePath, validProfile + "# changed after preflight\n");
        {
            EnvironmentGuard digest(profileSha256Environment, validProfileSha256);
            if (!rejectsCurrentProfile("invalid-profile-sha256-mismatch")) return 6;
        }
        if (!rejectsProfile(profilePath,
                            "profileVersion=1\navoidBuiltinMulticast=true\n",
                            "invalid-profile-missing-peer") ||
            !rejectsProfile(profilePath,
                            "profileVersion=1\nunknownKey=value\n",
                            "invalid-profile-unknown-key") ||
            !rejectsProfile(profilePath,
                            "profileVersion=1\nprofileVersion=1\n",
                            "invalid-profile-duplicate-key") ||
            !rejectsProfile(profilePath,
                            "profileVersion=1\nsharedMemory=yes\n",
                            "invalid-profile-boolean") ||
            !rejectsProfile(profilePath,
                            "profileVersion=1\ninitialPeers=127.0.0.1:70000\n",
                            "invalid-profile-port") ||
            !rejectsProfile(profilePath,
                            "profileVersion=1\nmaxInitialPeersRange=33\n",
                            "invalid-profile-range") ||
            !rejectsProfile(profilePath,
                            "profileVersion=2\n",
                            "invalid-profile-version") ||
            !rejectsProfile(profilePath,
                            "profileVersion=1\n#" + std::string(65536, 'x'),
                            "invalid-profile-size"))
            return 7;
    }
    std::filesystem::remove(profilePath);
    if (PocoDDS::FastDDS::Runtime::snapshots().size() != baseline) return 8;
    std::cout << "FAST_DDS_RUNTIME_SNAPSHOT_PASS deploymentProfile=verified "
                 "integrity=verified maxBytes=verified\n";
    return 0;
}
