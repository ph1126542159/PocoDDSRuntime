#include "PocoDDS/BundleManagement/BundleDeploymentCoordinator.h"
#include "PocoDDS/BundleManagement/BundleRepositoryFingerprint.h"
#include "PocoDDS/BundleManagement/BundleRepositoryRolloutGuard.h"

#include "Poco/DateTimeFormat.h"
#include "Poco/DateTimeFormatter.h"
#include "Poco/DirectoryIterator.h"
#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/Path.h"
#include "Poco/Process.h"
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

#include <map>
#include <limits>
#include <utility>

namespace PocoDDS::BundleManagement
{
namespace
{
using Properties = std::map<std::string, std::string>;

std::string jsonEscape(const std::string& value)
{
    std::string escaped;
    escaped.reserve(value.size());
    for (const char ch : value)
    {
        switch (ch)
        {
        case '\\': escaped += "\\\\"; break;
        case '"': escaped += "\\\""; break;
        case '\r': escaped += "\\r"; break;
        case '\n': escaped += "\\n"; break;
        case '\t': escaped += "\\t"; break;
        default: escaped += ch; break;
        }
    }
    return escaped;
}

Poco::Path childPath(const std::string& directory, const std::string& name)
{
    Poco::Path path(directory);
    path.makeDirectory();
    path.setFileName(name);
    return path;
}

Properties readProperties(const Poco::Path& path)
{
    Properties result;
    Poco::File file(path);
    if (!file.exists())
        return result;
    Poco::FileInputStream stream(path.toString());
    std::string line;
    while (std::getline(stream, line))
    {
        Poco::trimInPlace(line);
        if (line.empty() || line[0] == '#' || line[0] == '!')
            continue;
        const auto separator = line.find('=');
        if (separator == std::string::npos)
            continue;
        std::string key = line.substr(0, separator);
        std::string value = line.substr(separator + 1);
        Poco::trimInPlace(key);
        Poco::trimInPlace(value);
        result[key] = value;
    }
    return result;
}

std::string property(const Properties& values, const std::string& key,
                     const std::string& fallback = std::string())
{
    const auto iterator = values.find(key);
    return iterator == values.end() ? fallback : iterator->second;
}

std::uint64_t sequenceProperty(const Properties& values, const std::string& key)
{
    const std::string value = property(values, key);
    if (value.empty()) return 0;
    try
    {
        std::size_t consumed = 0;
        const auto parsed = std::stoull(value, &consumed, 10);
        if (consumed != value.size() ||
            parsed > static_cast<unsigned long long>(std::numeric_limits<std::int64_t>::max()))
            throw Poco::DataFormatException("Bundle deployment rollout sequence is invalid");
        return static_cast<std::uint64_t>(parsed);
    }
    catch (const Poco::Exception&)
    {
        throw;
    }
    catch (const std::exception&)
    {
        throw Poco::DataFormatException("Bundle deployment rollout sequence is malformed", value);
    }
}

void atomicWrite(const Poco::Path& target, const Properties& values)
{
    Poco::File(target.parent()).createDirectories();
    Poco::Path temporary(target);
    temporary.setFileName(target.getFileName() + ".tmp");
    {
        Poco::FileOutputStream stream(temporary.toString(), std::ios::out | std::ios::trunc);
        if (!stream.good())
            throw Poco::CreateFileException(temporary.toString());
        for (const auto& value : values)
            stream << value.first << '=' << value.second << '\n';
        stream.close();
    }
    std::string lastError;
    for (int attempt = 0; attempt < 100; ++attempt)
    {
        try
        {
            Poco::File targetFile(target);
            if (targetFile.exists())
                targetFile.remove();
            Poco::File(temporary).renameTo(target.toString());
            return;
        }
        catch (const Poco::Exception& exception)
        {
            lastError = exception.displayText();
            Poco::Thread::sleep(10);
        }
    }
    throw Poco::FileException("Cannot replace Bundle deployment state: " + lastError,
                              target.toString());
}

void appendAudit(const BundleDeploymentOptions& options, const BundleDeploymentStatus& status)
{
    Poco::File(options.stateDirectory).createDirectories();
    Poco::FileOutputStream stream(childPath(options.stateDirectory, "deployment-transactions.jsonl").toString(),
                                  std::ios::out | std::ios::app);
    if (!stream.good())
        throw Poco::CreateFileException(options.stateDirectory);
    stream << "{\"timestamp\":\""
           << jsonEscape(Poco::DateTimeFormatter::format(
                  Poco::Timestamp(), Poco::DateTimeFormat::ISO8601_FRAC_FORMAT))
           << "\",\"transactionId\":\"" << jsonEscape(status.transactionId)
           << "\",\"state\":\"" << jsonEscape(status.state)
           << "\",\"candidateDigest\":\"" << jsonEscape(status.candidateDigest)
           << "\",\"authorizationVerified\":"
           << (status.publisherId.empty() ? "false" : "true")
           << ",\"repositoryId\":\"" << jsonEscape(status.repositoryId)
           << "\",\"publisherId\":\"" << jsonEscape(status.publisherId)
           << "\",\"signingKeyId\":\"" << jsonEscape(status.signingKeyId)
           << "\",\"trustPolicyId\":\"" << jsonEscape(status.trustPolicyId)
           << "\",\"trustPolicySha256\":\"" << jsonEscape(status.trustPolicySha256)
           << "\",\"attestationSha256\":\"" << jsonEscape(status.attestationSha256)
           << "\",\"rolloutSequence\":" << status.rolloutSequence
           << ",\"releaseManifestSha256\":\"" << jsonEscape(status.releaseManifestSha256)
           << "\",\"sbomSha256\":\"" << jsonEscape(status.sbomSha256)
           << "\",\"artifactSetSha256\":\"" << jsonEscape(status.artifactSetSha256)
           << "\",\"releaseVersion\":\"" << jsonEscape(status.releaseVersion)
           << "\",\"gitCommit\":\"" << jsonEscape(status.gitCommit)
           << "\",\"builderId\":\"" << jsonEscape(status.builderId)
           << "\",\"buildProfile\":\"" << jsonEscape(status.buildProfile)
           << "\",\"error\":\"" << jsonEscape(status.error) << "\"}\n";
}

void writeStatus(const BundleDeploymentOptions& options, const BundleDeploymentStatus& status)
{
    // Audit is append-only evidence; deployment.properties is the authoritative
    // state machine. Append first so a failed audit write cannot leave callers
    // observing a transition that the operation reported as failed.
    appendAudit(options, status);
    atomicWrite(childPath(options.stateDirectory, "deployment.properties"),
                {{"error", status.error},
                 {"attestationSha256", status.attestationSha256},
                 {"authorizationVerified", status.publisherId.empty() ? "false" : "true"},
                 {"candidateDigest", status.candidateDigest},
                 {"publisherId", status.publisherId},
                 {"repositoryId", status.repositoryId},
                 {"rolloutSequence", std::to_string(status.rolloutSequence)},
                 {"releaseManifestSha256", status.releaseManifestSha256},
                 {"sbomSha256", status.sbomSha256},
                 {"artifactSetSha256", status.artifactSetSha256},
                 {"releaseVersion", status.releaseVersion},
                 {"gitCommit", status.gitCommit},
                 {"builderId", status.builderId},
                 {"buildProfile", status.buildProfile},
                 {"signingKeyId", status.signingKeyId},
                 {"state", status.state},
                 {"timestamp", Poco::DateTimeFormatter::format(
                                   Poco::Timestamp(), Poco::DateTimeFormat::ISO8601_FRAC_FORMAT)},
                 {"transactionId", status.transactionId},
                 {"trustPolicyId", status.trustPolicyId},
                 {"trustPolicySha256", status.trustPolicySha256}});
}

BundleDeploymentStatus makeStatus(
    const std::string& transactionId, const std::string& state,
    const std::string& candidateDigest, const std::string& error,
    const BundleRepositoryAuthorizationEvidence& authorization = {})
{
    BundleDeploymentStatus result;
    result.transactionId = transactionId;
    result.state = state;
    result.candidateDigest = candidateDigest;
    result.error = error;
    result.repositoryId = authorization.repositoryId;
    result.publisherId = authorization.publisherId;
    result.signingKeyId = authorization.keyId;
    result.trustPolicyId = authorization.policyId;
    result.trustPolicySha256 = authorization.policySha256;
    result.attestationSha256 = authorization.attestationSha256;
    result.rolloutSequence = authorization.rolloutSequence;
    result.releaseManifestSha256 = authorization.releaseManifestSha256;
    result.sbomSha256 = authorization.sbomSha256;
    result.artifactSetSha256 = authorization.artifactSetSha256;
    result.releaseVersion = authorization.releaseVersion;
    result.gitCommit = authorization.gitCommit;
    result.builderId = authorization.builderId;
    result.buildProfile = authorization.buildProfile;
    return result;
}

BundleRepositoryAuthorizationEvidence authorizationEvidence(
    const BundleDeploymentStatus& status)
{
    BundleRepositoryAuthorizationEvidence result;
    result.verified = !status.publisherId.empty();
    result.repositoryId = status.repositoryId;
    result.publisherId = status.publisherId;
    result.keyId = status.signingKeyId;
    result.policyId = status.trustPolicyId;
    result.policySha256 = status.trustPolicySha256;
    result.attestationSha256 = status.attestationSha256;
    result.rolloutSequence = status.rolloutSequence;
    result.releaseManifestSha256 = status.releaseManifestSha256;
    result.sbomSha256 = status.sbomSha256;
    result.artifactSetSha256 = status.artifactSetSha256;
    result.releaseVersion = status.releaseVersion;
    result.gitCommit = status.gitCommit;
    result.builderId = status.builderId;
    result.buildProfile = status.buildProfile;
    return result;
}

bool authorizationMatches(const BundleRepositoryAuthorizationEvidence& expected,
                          const BundleRepositoryAuthorizationEvidence& actual)
{
    return expected.verified == actual.verified &&
           expected.repositoryId == actual.repositoryId &&
           expected.publisherId == actual.publisherId && expected.keyId == actual.keyId &&
           expected.policyId == actual.policyId &&
           expected.policySha256 == actual.policySha256 &&
           expected.attestationSha256 == actual.attestationSha256 &&
           expected.rolloutSequence == actual.rolloutSequence &&
           expected.releaseManifestSha256 == actual.releaseManifestSha256 &&
           expected.sbomSha256 == actual.sbomSha256 &&
           expected.artifactSetSha256 == actual.artifactSetSha256 &&
           expected.releaseVersion == actual.releaseVersion &&
           expected.gitCommit == actual.gitCommit &&
           expected.builderId == actual.builderId &&
           expected.buildProfile == actual.buildProfile;
}

bool transactionAuthorizationMatches(
    const Properties& transaction,
    const BundleRepositoryAuthorizationEvidence& expected)
{
    return property(transaction, "authorizationVerified") == "true" &&
           property(transaction, "repositoryId") == expected.repositoryId &&
           property(transaction, "publisherId") == expected.publisherId &&
           property(transaction, "signingKeyId") == expected.keyId &&
           property(transaction, "trustPolicyId") == expected.policyId &&
           property(transaction, "trustPolicySha256") == expected.policySha256 &&
           property(transaction, "attestationSha256") == expected.attestationSha256 &&
           sequenceProperty(transaction, "rolloutSequence") == expected.rolloutSequence &&
           property(transaction, "releaseManifestSha256") == expected.releaseManifestSha256 &&
           property(transaction, "sbomSha256") == expected.sbomSha256 &&
           property(transaction, "artifactSetSha256") == expected.artifactSetSha256 &&
           property(transaction, "releaseVersion") == expected.releaseVersion &&
           property(transaction, "gitCommit") == expected.gitCommit &&
           property(transaction, "builderId") == expected.builderId &&
           property(transaction, "buildProfile") == expected.buildProfile;
}

void validateOptions(BundleDeploymentOptions& options)
{
    Poco::trimInPlace(options.repositoryDirectory);
    Poco::trimInPlace(options.stateDirectory);
    if (options.repositoryDirectory.empty() || options.stateDirectory.empty())
        throw Poco::InvalidArgumentException(
            "Bundle deployment requires repositoryDirectory and stateDirectory");
    Poco::Path repository(options.repositoryDirectory);
    repository.makeAbsolute();
    repository.makeDirectory();
    if (repository.depth() == 0)
        throw Poco::InvalidArgumentException("Bundle deployment repository cannot be a volume root",
                                             repository.toString());
    Poco::File repositoryFile(repository);
    if (!repositoryFile.exists() || !repositoryFile.isDirectory())
        throw Poco::FileNotFoundException("Bundle deployment repository directory",
                                          repository.toString());
    Poco::Path state(options.stateDirectory);
    state.makeAbsolute();
    state.makeDirectory();
    const std::string repositoryText = repository.toString();
    const std::string stateText = state.toString();
#if defined(POCO_OS_FAMILY_WINDOWS)
    if (Poco::icompare(stateText, 0, repositoryText.size(), repositoryText) == 0)
#else
    if (stateText.compare(0, repositoryText.size(), repositoryText) == 0)
#endif
        throw Poco::InvalidArgumentException(
            "Bundle deployment stateDirectory cannot be inside repositoryDirectory", stateText);
    options.repositoryDirectory = repository.toString();
    options.stateDirectory = state.toString();
}

void requireNonEmptyDirectory(const Poco::Path& path, const std::string& description)
{
    Poco::File directory(path);
    if (!directory.exists() || !directory.isDirectory())
        throw Poco::FileNotFoundException(description, path.toString());
    Poco::DirectoryIterator iterator(path), end;
    if (iterator == end)
        throw Poco::InvalidArgumentException(description + " is empty", path.toString());
}

void copyDirectory(const Poco::Path& source, const Poco::Path& destination)
{
    requireNonEmptyDirectory(source, "Bundle rollback repository");
    Poco::File target(destination);
    if (target.exists())
        target.remove(true);
    target.createDirectories();
    for (Poco::DirectoryIterator iterator(source), end; iterator != end; ++iterator)
    {
        Poco::Path child(destination);
        child.makeDirectory();
        child.setFileName(iterator.name());
        Poco::File(iterator->path()).copyTo(child.toString());
    }
}

Poco::Path rollbackPath(const BundleDeploymentOptions& options)
{
    return childPath(options.stateDirectory, "deployment-rollback");
}

Poco::Path lastKnownGoodPath(const BundleDeploymentOptions& options)
{
    return childPath(options.stateDirectory, "last-known-good");
}

Poco::Path siblingPath(const BundleDeploymentOptions& options, const std::string& suffix)
{
    Poco::Path repository(options.repositoryDirectory);
    repository.makeDirectory();
    Poco::Path sibling(repository.parent());
    sibling.makeDirectory();
    std::string name = repository[repository.depth() - 1];
    sibling.setFileName(name + suffix);
    return sibling;
}

void restoreRepository(const BundleDeploymentOptions& options)
{
    const Poco::Path rollback = rollbackPath(options);
    requireNonEmptyDirectory(rollback, "Bundle deployment rollback snapshot");
    const Poco::Path staging = siblingPath(options, ".pdr-restore-staging");
    const Poco::Path failed = siblingPath(options, ".pdr-failed");
    Poco::File stagingFile(staging);
    Poco::File failedFile(failed);
    Poco::File repository(options.repositoryDirectory);

    if (stagingFile.exists())
        stagingFile.remove(true);
    if (failedFile.exists())
        failedFile.remove(true);
    copyDirectory(rollback, staging);

    const std::string repositoryPath = repository.path();
    try
    {
        if (repository.exists())
            repository.renameTo(failed.toString());
        Poco::File(staging).renameTo(repositoryPath);
        if (failedFile.exists())
            failedFile.remove(true);
    }
    catch (...)
    {
        if (!Poco::File(repositoryPath).exists() && failedFile.exists())
            failedFile.renameTo(repositoryPath);
        throw;
    }
}

void removeRollbackSnapshot(const BundleDeploymentOptions& options)
{
    try
    {
        Poco::File rollback(rollbackPath(options));
        if (rollback.exists()) rollback.remove(true);
    }
    catch (...) {} // State is authoritative; the next activation replaces stale cleanup.
}

void verifyRollbackSnapshot(const BundleDeploymentOptions& options)
{
    if (!options.authorization.required)
        return;
    const auto accepted = BundleRepositoryRolloutGuard::state(options.stateDirectory);
    if (!accepted.initialized)
        throw Poco::IllegalStateException(
            "Authorized Bundle deployment requires an initialized rollout high-water mark");
    const std::string digest = BundleRepositoryFingerprint::calculateDirectory(
        rollbackPath(options).toString());
    if (digest != accepted.candidateDigest)
        throw Poco::InvalidAccessException(
            "Last-known-good Bundle snapshot does not match the accepted rollout digest",
            "expected " + accepted.candidateDigest + ", actual " + digest);
    const auto authorization = BundleRepositoryAuthorization::verify(
        rollbackPath(options).toString(), digest, options.authorization);
    BundleRepositoryRolloutGuard::verifyCandidate(
        options.stateDirectory, digest, authorization);
    if (authorization.rolloutSequence != accepted.rolloutSequence)
        throw Poco::InvalidAccessException(
            "Last-known-good Bundle snapshot rollout sequence does not match the high-water mark");
}
} // namespace

class BundleDeploymentCoordinator::Lease final
{
  public:
    Lease() = default;
    ~Lease() { release(); }

    bool held() const
    {
#if defined(POCO_OS_FAMILY_WINDOWS)
        return _handle != INVALID_HANDLE_VALUE;
#else
        return _descriptor >= 0;
#endif
    }

    void acquire(const std::string& path)
    {
        if (held()) return;
#if defined(POCO_OS_FAMILY_WINDOWS)
        std::wstring widePath;
        Poco::UnicodeConverter::toUTF16(path, widePath);
        _handle = CreateFileW(widePath.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                              OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (_handle == INVALID_HANDLE_VALUE)
            throw Poco::FileAccessDeniedException(
                "Bundle deployment lease is held by another Launcher", path);
        const std::string owner = "pid=" + std::to_string(Poco::Process::id()) + "\r\n";
        SetFilePointer(_handle, 0, nullptr, FILE_BEGIN);
        SetEndOfFile(_handle);
        DWORD written = 0;
        if (!WriteFile(_handle, owner.data(), static_cast<DWORD>(owner.size()), &written, nullptr) ||
            written != static_cast<DWORD>(owner.size()))
        {
            release();
            throw Poco::WriteFileException("Cannot record Bundle deployment lease owner", path);
        }
        FlushFileBuffers(_handle);
#else
        _descriptor = ::open(path.c_str(), O_RDWR | O_CREAT, 0660);
        if (_descriptor < 0 || ::flock(_descriptor, LOCK_EX | LOCK_NB) != 0)
        {
            if (_descriptor >= 0) ::close(_descriptor);
            _descriptor = -1;
            throw Poco::FileAccessDeniedException(
                "Bundle deployment lease is held by another Launcher", path);
        }
        const std::string owner = "pid=" + std::to_string(Poco::Process::id()) + "\n";
        if (::ftruncate(_descriptor, 0) != 0 ||
            ::write(_descriptor, owner.data(), owner.size()) != static_cast<ssize_t>(owner.size()) ||
            ::fsync(_descriptor) != 0)
        {
            release();
            throw Poco::WriteFileException("Cannot record Bundle deployment lease owner", path);
        }
#endif
    }

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

  private:
#if defined(POCO_OS_FAMILY_WINDOWS)
    HANDLE _handle{INVALID_HANDLE_VALUE};
#else
    int _descriptor{-1};
#endif
};

BundleDeploymentCoordinator::BundleDeploymentCoordinator(BundleDeploymentOptions options)
    : _options(std::move(options)), _lease(nullptr)
{
    validateOptions(_options);
    _lease = new Lease;
}

BundleDeploymentCoordinator::~BundleDeploymentCoordinator() { delete _lease; }

BundleDeploymentStatus BundleDeploymentCoordinator::status() const
{
    const Properties values = readProperties(childPath(_options.stateDirectory, "deployment.properties"));
    BundleDeploymentStatus result;
    result.transactionId = property(values, "transactionId");
    result.state = property(values, "state", "idle");
    result.candidateDigest = property(values, "candidateDigest");
    result.error = property(values, "error");
    result.repositoryId = property(values, "repositoryId");
    result.publisherId = property(values, "publisherId");
    result.signingKeyId = property(values, "signingKeyId");
    result.trustPolicyId = property(values, "trustPolicyId");
    result.trustPolicySha256 = property(values, "trustPolicySha256");
    result.attestationSha256 = property(values, "attestationSha256");
    result.rolloutSequence = sequenceProperty(values, "rolloutSequence");
    result.releaseManifestSha256 = property(values, "releaseManifestSha256");
    result.sbomSha256 = property(values, "sbomSha256");
    result.artifactSetSha256 = property(values, "artifactSetSha256");
    result.releaseVersion = property(values, "releaseVersion");
    result.gitCommit = property(values, "gitCommit");
    result.builderId = property(values, "builderId");
    result.buildProfile = property(values, "buildProfile");
    return result;
}

bool BundleDeploymentCoordinator::activationRequested() const
{
    const BundleDeploymentStatus deployment = status();
    const Properties transaction =
        readProperties(childPath(_options.stateDirectory, "transaction.properties"));
    const std::string transactionId = property(transaction, "transactionId");
    if (property(transaction, "state") != "restartRequired" || transactionId.empty())
        return false;
    if (deployment.transactionId == transactionId && deployment.state != "idle")
        return false;
    return true;
}

std::string BundleDeploymentCoordinator::beginActivation()
{
    _lease->acquire(childPath(_options.stateDirectory, "deployment.lock").toString());
    std::string transactionId;
    std::string candidateDigest;
    BundleRepositoryAuthorizationEvidence authorization;
    try
    {
        const Properties transaction =
            readProperties(childPath(_options.stateDirectory, "transaction.properties"));
        transactionId = property(transaction, "transactionId");
        candidateDigest = property(transaction, "candidateDigest");
        if (property(transaction, "state") != "restartRequired" || transactionId.empty())
            throw Poco::IllegalStateException("No restartRequired Bundle transaction is pending");
        if (candidateDigest.empty())
            throw Poco::IllegalStateException(
                "restartRequired Bundle transaction has no candidateDigest", transactionId);
        const std::string actualDigest =
            BundleRepositoryFingerprint::calculateDirectory(_options.repositoryDirectory);
        if (actualDigest != candidateDigest)
            throw Poco::DataFormatException(
                "Bundle repository changed after preflight",
                "expected " + candidateDigest + ", actual " + actualDigest);
        authorization = BundleRepositoryAuthorization::verify(
            _options.repositoryDirectory, candidateDigest, _options.authorization);
        if (_options.authorization.required)
            BundleRepositoryRolloutGuard::verifyCandidate(
                _options.stateDirectory, candidateDigest, authorization);
        if (_options.authorization.required &&
            !transactionAuthorizationMatches(transaction, authorization))
            throw Poco::InvalidAccessException(
                "Bundle transaction publisher authorization evidence does not match");

        copyDirectory(lastKnownGoodPath(_options), rollbackPath(_options));
        verifyRollbackSnapshot(_options);
        writeStatus(_options, makeStatus(transactionId, "activating", candidateDigest,
                                         std::string(), authorization));
        return transactionId;
    }
    catch (const Poco::Exception& exception)
    {
        if (!transactionId.empty())
        {
            try
            {
                writeStatus(_options, makeStatus(transactionId, "rejected", candidateDigest,
                                                 exception.displayText(), authorization));
            }
            catch (...) {}
        }
        _lease->release();
        throw;
    }
    catch (const std::exception& exception)
    {
        if (!transactionId.empty())
        {
            try
            {
                writeStatus(_options, makeStatus(transactionId, "rejected", candidateDigest,
                                                 exception.what(), authorization));
            }
            catch (...) {}
        }
        _lease->release();
        throw;
    }
    catch (...)
    {
        _lease->release();
        throw;
    }
}

bool BundleDeploymentCoordinator::activationReady(const std::string& transactionId) const
{
    const BundleDeploymentStatus deployment = status();
    if (deployment.state != "activating" || deployment.transactionId != transactionId ||
        deployment.candidateDigest.empty())
        return false;
    const Properties transaction =
        readProperties(childPath(_options.stateDirectory, "transaction.properties"));
    if (property(transaction, "transactionId") != transactionId ||
        property(transaction, "state") != "activationReady" ||
        property(transaction, "candidateDigest") != deployment.candidateDigest ||
        BundleRepositoryFingerprint::calculateDirectory(_options.repositoryDirectory) !=
            deployment.candidateDigest)
        return false;
    if (!_options.authorization.required)
        return true;
    const auto current = BundleRepositoryAuthorization::verify(
        _options.repositoryDirectory, deployment.candidateDigest, _options.authorization);
    BundleRepositoryRolloutGuard::verifyCandidate(
        _options.stateDirectory, deployment.candidateDigest, current);
    return authorizationMatches(authorizationEvidence(deployment), current) &&
           transactionAuthorizationMatches(transaction, current);
}

void BundleDeploymentCoordinator::commit(const std::string& transactionId)
{
    const BundleDeploymentStatus current = status();
    if (current.state != "activating" || current.transactionId != transactionId)
        throw Poco::IllegalStateException("Bundle deployment transaction is not activating", transactionId);
    if (!_lease->held())
        throw Poco::IllegalStateException("Bundle deployment lease is not held", transactionId);
    if (!activationReady(transactionId))
        throw Poco::IllegalStateException("Runtime has not acknowledged Bundle activation", transactionId);
    const auto authorization = authorizationEvidence(current);
    writeStatus(_options, makeStatus(transactionId, "committing", current.candidateDigest,
                                     std::string(), authorization));
    try
    {
        if (_options.authorization.required)
            BundleRepositoryRolloutGuard::commitCandidate(
                _options.stateDirectory, current.candidateDigest, authorization);
        writeStatus(_options, makeStatus(transactionId, "committed", current.candidateDigest,
                                         std::string(), authorization));
        removeRollbackSnapshot(_options);
        _lease->release();
    }
    catch (...)
    {
        // Once "committing" is durable, rollback is unsafe because the high-water
        // write may already have succeeded. A later Launcher resumes idempotently.
        _lease->release();
        throw;
    }
}

void BundleDeploymentCoordinator::rollback(const std::string& transactionId,
                                           const std::string& error)
{
    const BundleDeploymentStatus current = status();
    if (current.state != "activating" || current.transactionId != transactionId)
        throw Poco::IllegalStateException("Bundle deployment transaction is not activating", transactionId);
    if (!_lease->held())
        throw Poco::IllegalStateException("Bundle deployment lease is not held", transactionId);
    writeStatus(_options, makeStatus(transactionId, "rollingBack", current.candidateDigest,
                                     error, authorizationEvidence(current)));
    restoreRepository(_options);
    writeStatus(_options, makeStatus(transactionId, "rolledBack", current.candidateDigest,
                                     error, authorizationEvidence(current)));
    removeRollbackSnapshot(_options);
    _lease->release();
}

bool BundleDeploymentCoordinator::recoverInterruptedActivation()
{
    const BundleDeploymentStatus current = status();
    if (current.state != "activating" && current.state != "rollingBack" &&
        current.state != "committing")
        return false;

    _lease->acquire(childPath(_options.stateDirectory, "deployment.lock").toString());
    const BundleDeploymentStatus locked = status();
    if (locked.state != "activating" && locked.state != "rollingBack" &&
        locked.state != "committing")
    {
        _lease->release();
        return false;
    }

    if (locked.state == "committing")
    {
        const std::string digest = BundleRepositoryFingerprint::calculateDirectory(
            _options.repositoryDirectory);
        if (digest != locked.candidateDigest)
        {
            _lease->release();
            throw Poco::InvalidAccessException(
                "Cannot resume Bundle commit because repository content changed",
                "expected " + locked.candidateDigest + ", actual " + digest);
        }
        const auto authorization = BundleRepositoryAuthorization::verify(
            _options.repositoryDirectory, digest, _options.authorization);
        if (_options.authorization.required &&
            !authorizationMatches(authorizationEvidence(locked), authorization))
        {
            _lease->release();
            throw Poco::InvalidAccessException(
                "Cannot resume Bundle commit because authorization evidence changed");
        }
        if (_options.authorization.required)
            BundleRepositoryRolloutGuard::commitCandidate(
                _options.stateDirectory, digest, authorization);
        writeStatus(_options, makeStatus(locked.transactionId, "committed", digest,
                                         std::string(), authorization));
        removeRollbackSnapshot(_options);
        _lease->release();
        return true;
    }

    // Convert rollingBack back to activating so rollback() can resume idempotently.
    if (locked.state == "rollingBack")
        writeStatus(_options, makeStatus(locked.transactionId, "activating",
                                         locked.candidateDigest, locked.error,
                                         authorizationEvidence(locked)));
    rollback(locked.transactionId,
             locked.error.empty() ? "launcher recovered interrupted Bundle activation" : locked.error);
    return true;
}
} // namespace PocoDDS::BundleManagement
