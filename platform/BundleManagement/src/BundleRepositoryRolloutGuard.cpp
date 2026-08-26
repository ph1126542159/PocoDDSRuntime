#include "PocoDDS/BundleManagement/BundleRepositoryRolloutGuard.h"

#include "Poco/DateTimeFormat.h"
#include "Poco/DateTimeFormatter.h"
#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/Path.h"
#include "Poco/Platform.h"
#include "Poco/String.h"
#include "Poco/Thread.h"
#include "Poco/Timestamp.h"

#if defined(POCO_OS_FAMILY_WINDOWS)
#include "Poco/UnicodeConverter.h"
#include <Windows.h>
#else
#include <cerrno>
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#endif

#include <fstream>
#include <limits>
#include <map>
#include <regex>
#include <string>

namespace PocoDDS::BundleManagement
{
namespace
{
using Properties = std::map<std::string, std::string>;

Poco::Path childPath(const std::string& directory, const std::string& name)
{
    Poco::Path path(directory);
    path.makeDirectory();
    path.setFileName(name);
    return path;
}

void requireStateDirectory(const std::string& directory)
{
    if (directory.empty())
        throw Poco::InvalidArgumentException(
            "Bundle rollout protection requires a state directory");
    Poco::Path path(directory);
    path.makeAbsolute();
    if (path.depth() == 0)
        throw Poco::InvalidArgumentException(
            "Bundle rollout state directory cannot be a volume root", directory);
    Poco::File(directory).createDirectories();
}

bool isSha256(const std::string& value)
{
    return std::regex_match(value, std::regex("^[0-9a-f]{64}$"));
}

bool isGitCommit(const std::string& value)
{
    return std::regex_match(value, std::regex("^(?:[0-9a-f]{40}|[0-9a-f]{64})$"));
}

bool safePropertyValue(const std::string& value)
{
    return !value.empty() && value.find_first_of("\r\n") == std::string::npos;
}

std::uint64_t positiveSequence(const std::string& value)
{
    try
    {
        std::size_t consumed = 0;
        const auto parsed = std::stoull(value, &consumed, 10);
        if (consumed != value.size() || parsed == 0 ||
            parsed > static_cast<unsigned long long>(std::numeric_limits<std::int64_t>::max()))
            throw Poco::DataFormatException("Bundle rollout sequence is outside the supported range");
        return static_cast<std::uint64_t>(parsed);
    }
    catch (const Poco::Exception&)
    {
        throw;
    }
    catch (const std::exception&)
    {
        throw Poco::DataFormatException("Bundle rollout sequence is malformed", value);
    }
}

Properties readProperties(const Poco::Path& path)
{
    Properties result;
    Poco::File file(path);
    if (!file.exists())
        return result;
    if (!file.isFile())
        throw Poco::DataFormatException("Bundle rollout high-water mark is not a file",
                                        path.toString());
    Poco::FileInputStream stream(path.toString());
    if (!stream.good())
        throw Poco::OpenFileException("Cannot open Bundle rollout high-water mark",
                                      path.toString());
    std::string line;
    while (std::getline(stream, line))
    {
        Poco::trimInPlace(line);
        if (line.empty() || line[0] == '#' || line[0] == '!')
            continue;
        const auto separator = line.find('=');
        if (separator == std::string::npos)
            throw Poco::DataFormatException("Bundle rollout high-water mark line is malformed",
                                            line);
        std::string key = line.substr(0, separator);
        std::string value = line.substr(separator + 1);
        Poco::trimInPlace(key);
        Poco::trimInPlace(value);
        if (key.empty() || !result.emplace(key, value).second)
            throw Poco::DataFormatException(
                "Bundle rollout high-water mark contains an empty or duplicate key", key);
    }
    return result;
}

const std::string& required(const Properties& values, const std::string& key)
{
    const auto found = values.find(key);
    if (found == values.end() || found->second.empty())
        throw Poco::DataFormatException(
            "Bundle rollout high-water mark is missing a required field", key);
    return found->second;
}

BundleRepositoryRolloutState readStateUnlocked(const std::string& directory)
{
    const Properties values = readProperties(
        childPath(directory, "repository-rollout-high-water.properties"));
    if (values.empty())
        return {};
    const std::string schemaVersion = required(values, "schemaVersion");
    if (schemaVersion != "1" && schemaVersion != "2")
        throw Poco::DataFormatException("Unsupported Bundle rollout high-water schema");

    BundleRepositoryRolloutState result;
    result.initialized = true;
    result.repositoryId = required(values, "repositoryId");
    result.rolloutSequence = positiveSequence(required(values, "rolloutSequence"));
    result.candidateDigest = required(values, "candidateDigest");
    result.publisherId = required(values, "publisherId");
    result.signingKeyId = required(values, "signingKeyId");
    result.trustPolicyId = required(values, "trustPolicyId");
    result.trustPolicySha256 = required(values, "trustPolicySha256");
    result.attestationSha256 = required(values, "attestationSha256");
    if (!isSha256(result.candidateDigest) || !isSha256(result.trustPolicySha256) ||
        !isSha256(result.attestationSha256))
        throw Poco::DataFormatException(
            "Bundle rollout high-water mark contains an invalid SHA-256");
    if (schemaVersion == "2")
    {
        result.provenanceBound = true;
        result.releaseManifestSha256 = required(values, "releaseManifestSha256");
        result.sbomSha256 = required(values, "sbomSha256");
        result.artifactSetSha256 = required(values, "artifactSetSha256");
        result.releaseVersion = required(values, "releaseVersion");
        result.gitCommit = required(values, "gitCommit");
        result.builderId = required(values, "builderId");
        result.buildProfile = required(values, "buildProfile");
        if (!isSha256(result.releaseManifestSha256) || !isSha256(result.sbomSha256) ||
            !isSha256(result.artifactSetSha256) || !isGitCommit(result.gitCommit))
            throw Poco::DataFormatException(
                "Bundle rollout high-water provenance is malformed");
    }
    return result;
}

void validateAuthorization(const std::string& digest,
                           const BundleRepositoryAuthorizationEvidence& authorization)
{
    if (!authorization.verified || authorization.repositoryId.empty() ||
        authorization.publisherId.empty() || authorization.keyId.empty() ||
        authorization.policyId.empty() || !isSha256(authorization.policySha256) ||
        !isSha256(authorization.attestationSha256) || authorization.rolloutSequence == 0 ||
        !isSha256(authorization.releaseManifestSha256) ||
        !isSha256(authorization.sbomSha256) ||
        !isSha256(authorization.artifactSetSha256) ||
        !safePropertyValue(authorization.releaseVersion) ||
        !isGitCommit(authorization.gitCommit) ||
        !safePropertyValue(authorization.builderId) ||
        !safePropertyValue(authorization.buildProfile) ||
        authorization.rolloutSequence >
            static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) ||
        !isSha256(digest))
        throw Poco::InvalidArgumentException(
            "Bundle rollout protection requires complete verified authorization evidence");
}

void verifyAgainst(const BundleRepositoryRolloutState& current,
                   const std::string& digest,
                   const BundleRepositoryAuthorizationEvidence& authorization)
{
    validateAuthorization(digest, authorization);
    if (!current.initialized)
        return;
    if (current.repositoryId != authorization.repositoryId)
        throw Poco::InvalidAccessException(
            "Bundle rollout repository identity does not match the high-water mark",
            authorization.repositoryId);
    if (authorization.rolloutSequence < current.rolloutSequence)
        throw Poco::InvalidAccessException(
            "Bundle repository rollback detected",
            "candidate sequence " + std::to_string(authorization.rolloutSequence) +
                ", accepted high-water " + std::to_string(current.rolloutSequence));
    if (authorization.rolloutSequence == current.rolloutSequence &&
        digest != current.candidateDigest)
        throw Poco::InvalidAccessException(
            "Bundle rollout sequence was reused for different repository content",
            std::to_string(authorization.rolloutSequence));
}

class ExclusiveStateLease final
{
  public:
    explicit ExclusiveStateLease(const std::string& path)
    {
        for (int attempt = 0; attempt < 100; ++attempt)
        {
#if defined(POCO_OS_FAMILY_WINDOWS)
            std::wstring wide;
            Poco::UnicodeConverter::toUTF16(path, wide);
            _handle = CreateFileW(wide.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                                  OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
            if (_handle != INVALID_HANDLE_VALUE)
                return;
#else
            if (_descriptor < 0)
                _descriptor = ::open(path.c_str(), O_RDWR | O_CREAT, 0660);
            if (_descriptor >= 0 && ::flock(_descriptor, LOCK_EX | LOCK_NB) == 0)
                return;
#endif
            Poco::Thread::sleep(10);
        }
        release();
        throw Poco::FileAccessDeniedException(
            "Bundle rollout high-water lease is held by another process", path);
    }

    ~ExclusiveStateLease() { release(); }

  private:
    void release()
    {
#if defined(POCO_OS_FAMILY_WINDOWS)
        if (_handle != INVALID_HANDLE_VALUE)
        {
            CloseHandle(_handle);
            _handle = INVALID_HANDLE_VALUE;
        }
#else
        if (_descriptor >= 0)
        {
            ::flock(_descriptor, LOCK_UN);
            ::close(_descriptor);
            _descriptor = -1;
        }
#endif
    }

#if defined(POCO_OS_FAMILY_WINDOWS)
    HANDLE _handle{INVALID_HANDLE_VALUE};
#else
    int _descriptor{-1};
#endif
};

void flushFile(const std::string& path)
{
#if defined(POCO_OS_FAMILY_WINDOWS)
    std::wstring wide;
    Poco::UnicodeConverter::toUTF16(path, wide);
    HANDLE handle = CreateFileW(wide.c_str(), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                                OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (handle == INVALID_HANDLE_VALUE || !FlushFileBuffers(handle))
    {
        if (handle != INVALID_HANDLE_VALUE) CloseHandle(handle);
        throw Poco::WriteFileException("Cannot flush Bundle rollout high-water mark", path);
    }
    CloseHandle(handle);
#else
    const int descriptor = ::open(path.c_str(), O_RDONLY);
    if (descriptor < 0 || ::fsync(descriptor) != 0)
    {
        if (descriptor >= 0) ::close(descriptor);
        throw Poco::WriteFileException("Cannot flush Bundle rollout high-water mark", path);
    }
    ::close(descriptor);
#endif
}

void replaceFile(const std::string& temporary, const std::string& target)
{
#if defined(POCO_OS_FAMILY_WINDOWS)
    std::wstring wideTemporary;
    std::wstring wideTarget;
    Poco::UnicodeConverter::toUTF16(temporary, wideTemporary);
    Poco::UnicodeConverter::toUTF16(target, wideTarget);
    if (!MoveFileExW(wideTemporary.c_str(), wideTarget.c_str(),
                     MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw Poco::FileException("Cannot atomically replace Bundle rollout high-water mark",
                                  target);
#else
    if (::rename(temporary.c_str(), target.c_str()) != 0)
        throw Poco::FileException("Cannot atomically replace Bundle rollout high-water mark",
                                  target);
    const Poco::Path targetPath(target);
    const int directory = ::open(targetPath.parent().toString().c_str(), O_RDONLY | O_DIRECTORY);
    if (directory < 0 || ::fsync(directory) != 0)
    {
        if (directory >= 0) ::close(directory);
        throw Poco::WriteFileException("Cannot flush Bundle rollout state directory",
                                       targetPath.parent().toString());
    }
    ::close(directory);
#endif
}

void writeStateUnlocked(const std::string& directory,
                        const std::string& digest,
                        const BundleRepositoryAuthorizationEvidence& authorization)
{
    const Poco::Path target = childPath(directory, "repository-rollout-high-water.properties");
    Poco::Path temporary(target);
    temporary.setFileName(target.getFileName() + ".tmp");
    {
        std::ofstream stream(temporary.toString(), std::ios::out | std::ios::trunc | std::ios::binary);
        if (!stream.good())
            throw Poco::CreateFileException(temporary.toString());
        stream << "schemaVersion=2\n"
               << "repositoryId=" << authorization.repositoryId << '\n'
               << "rolloutSequence=" << authorization.rolloutSequence << '\n'
               << "candidateDigest=" << digest << '\n'
               << "publisherId=" << authorization.publisherId << '\n'
               << "signingKeyId=" << authorization.keyId << '\n'
               << "trustPolicyId=" << authorization.policyId << '\n'
               << "trustPolicySha256=" << authorization.policySha256 << '\n'
               << "attestationSha256=" << authorization.attestationSha256 << '\n'
               << "releaseManifestSha256=" << authorization.releaseManifestSha256 << '\n'
               << "sbomSha256=" << authorization.sbomSha256 << '\n'
               << "artifactSetSha256=" << authorization.artifactSetSha256 << '\n'
               << "releaseVersion=" << authorization.releaseVersion << '\n'
               << "gitCommit=" << authorization.gitCommit << '\n'
               << "builderId=" << authorization.builderId << '\n'
               << "buildProfile=" << authorization.buildProfile << '\n'
               << "timestamp=" << Poco::DateTimeFormatter::format(
                      Poco::Timestamp(), Poco::DateTimeFormat::ISO8601_FRAC_FORMAT) << '\n';
        stream.flush();
        if (!stream.good())
            throw Poco::WriteFileException(temporary.toString());
    }
    flushFile(temporary.toString());
    replaceFile(temporary.toString(), target.toString());
}
} // namespace

BundleRepositoryRolloutState BundleRepositoryRolloutGuard::state(
    const std::string& stateDirectory)
{
    requireStateDirectory(stateDirectory);
    ExclusiveStateLease lease(
        childPath(stateDirectory, "repository-rollout-high-water.lock").toString());
    return readStateUnlocked(stateDirectory);
}

void BundleRepositoryRolloutGuard::verifyCandidate(
    const std::string& stateDirectory,
    const std::string& candidateDigest,
    const BundleRepositoryAuthorizationEvidence& authorization)
{
    requireStateDirectory(stateDirectory);
    ExclusiveStateLease lease(
        childPath(stateDirectory, "repository-rollout-high-water.lock").toString());
    verifyAgainst(readStateUnlocked(stateDirectory), candidateDigest, authorization);
}

BundleRepositoryRolloutState BundleRepositoryRolloutGuard::commitCandidate(
    const std::string& stateDirectory,
    const std::string& candidateDigest,
    const BundleRepositoryAuthorizationEvidence& authorization)
{
    requireStateDirectory(stateDirectory);
    ExclusiveStateLease lease(
        childPath(stateDirectory, "repository-rollout-high-water.lock").toString());
    const auto current = readStateUnlocked(stateDirectory);
    verifyAgainst(current, candidateDigest, authorization);
    if (!current.initialized || !current.provenanceBound ||
        authorization.rolloutSequence > current.rolloutSequence)
        writeStateUnlocked(stateDirectory, candidateDigest, authorization);
    return readStateUnlocked(stateDirectory);
}
} // namespace PocoDDS::BundleManagement
