#include "PocoDDS/BundleManagement/BundleManager.h"
#include "PocoDDS/BundleManagement/BundleRepositoryFingerprint.h"
#include "PocoDDS/BundleManagement/BundleRepositoryRolloutGuard.h"

#include "Poco/DirectoryIterator.h"
#include "Poco/DateTimeFormatter.h"
#include "Poco/DateTimeFormat.h"
#include "Poco/Event.h"
#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/Glob.h"
#include "Poco/Logger.h"
#include "Poco/NumberFormatter.h"
#include "Poco/OSP/BundleLoader.h"
#include "Poco/OSP/BundleRepository.h"
#include "Poco/OSP/OSPSubsystem.h"
#include "Poco/OSP/OSPException.h"
#include "Poco/Path.h"
#include "Poco/String.h"
#include "Poco/StringTokenizer.h"
#include "Poco/Thread.h"
#include "Poco/Timestamp.h"
#include "Poco/UUIDGenerator.h"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <filesystem>
#include <map>
#include <mutex>
#include <sstream>
#include <set>
#include <thread>
#include <utility>

namespace PocoDDS::BundleManagement
{
class BundleManager::Impl final
{
  public:
    using Snapshot =
        std::map<std::string, std::pair<Poco::Timestamp::TimeVal, Poco::File::FileSize>>;

    Impl(Poco::OSP::OSPSubsystem& osp, Poco::Logger& logger, BundleManagerOptions options)
        : _osp(osp), _logger(logger), _options(std::move(options))
    {
        _options.intervalMilliseconds = std::max<std::int64_t>(250, _options.intervalMilliseconds);
        _options.stableScanCount = std::max<std::size_t>(2, _options.stableScanCount);
        if (_options.stateDirectory.empty())
            _options.stateDirectory = defaultStateDirectory();
        validateStateDirectoryBoundary();
    }

    ~Impl() { stop(); }

    void start()
    {
        bool expected = false;
        if (!_running.compare_exchange_strong(expected, true))
            return;

        try
        {
            initializeTransactionState();
        }
        catch (...)
        {
            _running = false;
            throw;
        }

        _stop.reset();
        _worker = std::thread([this] { monitor(); });
        _logger.information("Bundle manager watching '%s' every %Ld ms.",
                            _options.repositories,
                            static_cast<long long>(_options.intervalMilliseconds));
    }

    void stop()
    {
        if (!_running.exchange(false))
            return;
        _stop.set();
        if (_worker.joinable())
            _worker.join();
    }

    void reload()
    {
        std::lock_guard<std::mutex> guard(_reloadMutex);
        const std::string transactionId = Poco::UUIDGenerator::defaultGenerator().createRandom().toString();
        bool runtimeTouched = false;
        try
        {
            _logger.information("Bundle repository changed; preflighting transaction %s.", transactionId);
            // Authenticate the exact bytes before asking OSP to parse any Bundle archive or
            // manifest. This keeps unsigned input outside the native Bundle parser boundary.
            const std::string candidateDigest = repositoryDirectoryDigest();
            const auto authorization = repositoryAuthorization(candidateDigest);
            verifyRollout(candidateDigest, authorization);
            Poco::OSP::BundleRepository repository(_options.repositories, _osp.bundleLoader(),
                                                   _osp.getBundleFilter());
            const Poco::OSP::BundleRepository::Bundles candidates = repository.validateBundles();
            if (candidates.empty())
                throw Poco::InvalidArgumentException("Bundle repository preflight selected no bundles");

            if (!_options.inProcessReloadEnabled)
            {
                writeJournal(transactionId, "restartRequired", candidates.size(), std::string(),
                             candidateDigest, authorization);
                appendAudit(transactionId, "restartRequired", candidates.size(), std::string(),
                            candidateDigest, authorization);
                clearError();
                ++_restartRequiredReloads;
                _logger.warning(
                    "Bundle repository transaction %s passed preflight and requires a process restart; "
                    "in-process native Bundle reload is disabled.",
                    transactionId);
                return;
            }

            writeJournal(transactionId, "prepared", candidates.size(), std::string(), candidateDigest,
                         authorization);
            writeJournal(transactionId, "applying", candidates.size(), std::string(), candidateDigest,
                         authorization);
            runtimeTouched = true;
            activate(candidates);
            commitBackup(candidates, candidateDigest, authorization);
            commitRollout(candidateDigest, authorization);
            writeJournal(transactionId, "committed", candidates.size(), std::string(), candidateDigest,
                         authorization);
            appendAudit(transactionId, "committed", candidates.size(), std::string(), candidateDigest,
                        authorization);
            clearError();
            ++_successfulReloads;
            _logger.information("Bundle repository transaction %s committed with %z bundles.",
                                transactionId, candidates.size());
        }
        catch (const Poco::Exception& exception)
        {
            handleFailure(transactionId, runtimeTouched, exception.displayText());
            throw;
        }
        catch (const std::exception& exception)
        {
            handleFailure(transactionId, runtimeTouched, exception.what());
            throw;
        }
    }

    bool running() const { return _running.load(); }
    std::size_t successfulReloads() const { return _successfulReloads.load(); }
    std::size_t failedReloads() const { return _failedReloads.load(); }
    std::size_t rejectedReloads() const { return _rejectedReloads.load(); }
    std::size_t rolledBackReloads() const { return _rolledBackReloads.load(); }
    std::size_t restartRequiredReloads() const { return _restartRequiredReloads.load(); }
    std::string lastError() const
    {
        std::lock_guard<std::mutex> guard(_errorMutex);
        return _lastError;
    }

  private:
    static std::string jsonEscape(const std::string& value)
    {
        std::string escaped;
        escaped.reserve(value.size());
        for (char ch : value)
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

    std::string defaultStateDirectory() const
    {
#if defined(POCO_OS_FAMILY_UNIX)
        const std::string separators(":;");
#else
        const std::string separators(";");
#endif
        Poco::StringTokenizer paths(_options.repositories, separators,
                                    Poco::StringTokenizer::TOK_IGNORE_EMPTY |
                                        Poco::StringTokenizer::TOK_TRIM);
        if (paths.begin() == paths.end())
            throw Poco::InvalidArgumentException("Bundle manager requires a repository path");

        Poco::Path repository(*paths.begin());
        repository.makeAbsolute();
        Poco::File repositoryFile(repository);
        if ((repositoryFile.exists() && repositoryFile.isFile()) ||
            Poco::icompare(repository.getExtension(), "bndl") == 0 ||
            repository.toString().find_first_of("*?") != std::string::npos)
            repository = repository.parent();
        Poco::Path state = repository.parent();
        state.pushDirectory("data");
        state.pushDirectory("bundle-manager");
        state.makeDirectory();
        return state.toString();
    }

    Poco::Path statePath(const std::string& name) const
    {
        Poco::Path path(_options.stateDirectory);
        path.makeDirectory();
        path.setFileName(name);
        return path;
    }

    Poco::Path backupPath() const { return statePath("last-known-good"); }
    Poco::Path stagingPath() const { return statePath("last-known-good.staging"); }
    Poco::Path previousPath() const { return statePath("last-known-good.previous"); }

    static std::string canonicalDirectory(const std::string& value)
    {
        std::string result = std::filesystem::weakly_canonical(
            std::filesystem::absolute(std::filesystem::u8path(value))).generic_u8string();
#if defined(POCO_OS_FAMILY_WINDOWS)
        std::transform(result.begin(), result.end(), result.begin(), [](unsigned char character) {
            return static_cast<char>(std::tolower(character));
        });
#endif
        while (result.size() > 1 && result.back() == '/') result.pop_back();
        return result;
    }

    static bool sameOrChild(const std::string& parent, const std::string& candidate)
    {
        return candidate == parent ||
               (candidate.size() > parent.size() &&
                candidate.compare(0, parent.size(), parent) == 0 &&
                candidate[parent.size()] == '/');
    }

    void validateStateDirectoryBoundary() const
    {
        const std::string directory = repositoryDirectory();
        if (directory.empty())
            return;
        const std::string repository = canonicalDirectory(directory);
        const std::string state = canonicalDirectory(_options.stateDirectory);
        if (sameOrChild(repository, state))
            throw Poco::InvalidArgumentException(
                "Bundle manager stateDirectory cannot be inside repositoryDirectory",
                _options.stateDirectory);
    }

    void ensureStateDirectory() const
    {
        Poco::File(_options.stateDirectory).createDirectories();
    }

    void recoverBackupSwap()
    {
        ensureStateDirectory();
        Poco::File active(backupPath());
        Poco::File previous(previousPath());
        Poco::File staging(stagingPath());
        if (!active.exists() && previous.exists())
            previous.renameTo(active.path());
        else if (active.exists() && previous.exists())
            previous.remove(true);
        if (staging.exists())
            staging.remove(true);
    }

    bool backupAvailable() const
    {
        Poco::File backup(backupPath());
        if (!backup.exists() || !backup.isDirectory())
            return false;
        Poco::DirectoryIterator iterator(backup.path()), end;
        return iterator != end;
    }

    struct DeploymentTransaction
    {
        std::string transactionId;
        std::string state;
        std::string candidateDigest;
    };

    std::string repositoryDirectory() const
    {
#if defined(POCO_OS_FAMILY_UNIX)
        const std::string separators(":;");
#else
        const std::string separators(";");
#endif
        Poco::StringTokenizer paths(_options.repositories, separators,
                                    Poco::StringTokenizer::TOK_IGNORE_EMPTY |
                                        Poco::StringTokenizer::TOK_TRIM);
        if (paths.count() != 1)
            return {};
        const std::string path = *paths.begin();
        if (path.find_first_of("*?") != std::string::npos)
            return {};
        Poco::File repository(path);
        if (!repository.exists() || !repository.isDirectory())
            return {};
        Poco::Path absolute(path);
        absolute.makeAbsolute();
        absolute.makeDirectory();
        return absolute.toString();
    }

    std::string repositoryDirectoryDigest() const
    {
        const std::string directory = repositoryDirectory();
        return directory.empty() ? std::string() :
                                   BundleRepositoryFingerprint::calculateDirectory(directory);
    }

    BundleRepositoryAuthorizationEvidence repositoryAuthorization(
        const std::string& candidateDigest) const
    {
        if (!_options.authorization.required)
            return {};
        const std::string directory = repositoryDirectory();
        if (directory.empty())
            throw Poco::InvalidArgumentException(
                "Required Bundle authorization supports one literal directory repository");
        return BundleRepositoryAuthorization::verify(
            directory, candidateDigest, _options.authorization);
    }

    void verifyRollout(
        const std::string& candidateDigest,
        const BundleRepositoryAuthorizationEvidence& authorization) const
    {
        if (_options.authorization.required)
            BundleRepositoryRolloutGuard::verifyCandidate(
                _options.stateDirectory, candidateDigest, authorization);
    }

    void commitRollout(
        const std::string& candidateDigest,
        const BundleRepositoryAuthorizationEvidence& authorization) const
    {
        if (_options.authorization.required)
            BundleRepositoryRolloutGuard::commitCandidate(
                _options.stateDirectory, candidateDigest, authorization);
    }

    DeploymentTransaction deploymentTransaction() const
    {
        const Poco::Path path = statePath("deployment.properties");
        if (!Poco::File(path).exists())
            return {};

        Poco::FileInputStream stream(path.toString());
        DeploymentTransaction transaction;
        std::string line;
        while (std::getline(stream, line))
        {
            const auto separator = line.find('=');
            if (separator == std::string::npos)
                continue;
            std::string key = line.substr(0, separator);
            std::string value = line.substr(separator + 1);
            Poco::trimInPlace(key);
            Poco::trimInPlace(value);
            if (key == "transactionId") transaction.transactionId = value;
            else if (key == "state") transaction.state = value;
            else if (key == "candidateDigest") transaction.candidateDigest = value;
        }
        return transaction;
    }

    void initializeTransactionState()
    {
        std::lock_guard<std::mutex> guard(_reloadMutex);
        recoverBackupSwap();
        // Runtime startup uses the same authorization-before-parsing boundary as reload.
        const std::string candidateDigest = repositoryDirectoryDigest();
        const auto authorization = repositoryAuthorization(candidateDigest);
        verifyRollout(candidateDigest, authorization);
        Poco::OSP::BundleRepository repository(_options.repositories, _osp.bundleLoader(),
                                               _osp.getBundleFilter());
        const Poco::OSP::BundleRepository::Bundles candidates = repository.validateBundles();
        if (candidates.empty())
            throw Poco::InvalidArgumentException("Bundle repository preflight selected no bundles");
        const auto deployment = deploymentTransaction();
        if (!deployment.transactionId.empty() && deployment.state == "activating")
        {
            if (deployment.candidateDigest.empty() || candidateDigest.empty() ||
                deployment.candidateDigest != candidateDigest)
                throw Poco::DataFormatException(
                    "Bundle deployment candidate digest mismatch",
                    "transaction " + deployment.transactionId + ", expected " +
                        deployment.candidateDigest + ", actual " + candidateDigest);
        }
        verifyRuntime(candidates);
        commitBackup(candidates, candidateDigest, authorization);
        if (!deployment.transactionId.empty() && deployment.state == "activating")
        {
            writeJournal(deployment.transactionId, "activationReady", candidates.size(), std::string(),
                         candidateDigest, authorization);
            appendAudit(deployment.transactionId, "activationReady", candidates.size(), std::string(),
                        candidateDigest, authorization);
            _logger.information(
                "Bundle deployment transaction %s passed Runtime startup verification.",
                deployment.transactionId);
        }
        else
        {
            commitRollout(candidateDigest, authorization);
            writeJournal("startup", "committed", candidates.size(), std::string(), candidateDigest,
                         authorization);
        }
    }

    void activate(const Poco::OSP::BundleRepository::Bundles& candidates)
    {
        auto& loader = _osp.bundleLoader();
        loader.stopAllBundles();
        loader.unloadAllBundles();
        for (const auto& candidate : candidates)
            loader.loadBundle(candidate);
        loader.resolveAllBundles();
        verifyResolved(candidates);
        loader.startAllBundles();
        verifyRuntime(candidates);
    }

    void verifyResolved(const Poco::OSP::BundleRepository::Bundles& candidates) const
    {
        for (const auto& candidate : candidates)
        {
            if (!candidate->isResolved())
                throw Poco::OSP::BundleResolveException(
                    "Bundle repository transaction left a bundle unresolved",
                    candidate->symbolicName() + "/" + candidate->version().toString());
        }
    }

    void verifyRuntime(const Poco::OSP::BundleRepository::Bundles& candidates) const
    {
        std::vector<Poco::OSP::Bundle::Ptr> loaded;
        _osp.bundleLoader().listBundles(loaded);
        if (loaded.size() != candidates.size())
            throw Poco::OSP::BundleLoadException(
                "Bundle repository topology count mismatch",
                "expected " + Poco::NumberFormatter::format(candidates.size()) +
                    ", loaded " + Poco::NumberFormatter::format(loaded.size()));

        for (const auto& candidate : candidates)
        {
            Poco::OSP::Bundle::Ptr actual(_osp.bundleLoader().findBundle(candidate->symbolicName()));
            if (actual.isNull() || actual->version() != candidate->version())
                throw Poco::OSP::BundleLoadException(
                    "Bundle repository topology mismatch",
                    candidate->symbolicName() + "/" + candidate->version().toString());
            if (!actual->isResolved())
                throw Poco::OSP::BundleResolveException(
                    "Bundle repository health gate found an unresolved bundle",
                    actual->symbolicName());
            if (!actual->lazyStart() && !actual->autoStartBlocked() && !actual->isActive())
                throw Poco::OSP::BundleStateException(
                    "Bundle repository health gate found an inactive bundle",
                    actual->symbolicName());
        }
    }

    void writeBackupMetadata(
        const std::string& candidateDigest,
        const BundleRepositoryAuthorizationEvidence& authorization) const
    {
        const Poco::Path target = statePath("last-known-good.properties");
        Poco::Path temporary(target);
        temporary.setFileName(target.getFileName() + ".tmp");
        {
            Poco::FileOutputStream stream(temporary.toString(), std::ios::out | std::ios::trunc);
            if (!stream.good())
                throw Poco::CreateFileException(temporary.toString());
            stream << "schemaVersion=2\n"
                   << "candidateDigest=" << candidateDigest << "\n"
                   << "authorizationVerified=" << (authorization.verified ? "true" : "false") << "\n"
                   << "repositoryId=" << authorization.repositoryId << "\n"
                   << "rolloutSequence=" << authorization.rolloutSequence << "\n"
                   << "publisherId=" << authorization.publisherId << "\n"
                   << "signingKeyId=" << authorization.keyId << "\n"
                   << "trustPolicyId=" << authorization.policyId << "\n"
                   << "trustPolicySha256=" << authorization.policySha256 << "\n"
                   << "attestationSha256=" << authorization.attestationSha256 << "\n";
            stream << "releaseManifestSha256=" << authorization.releaseManifestSha256 << "\n"
                   << "sbomSha256=" << authorization.sbomSha256 << "\n"
                   << "artifactSetSha256=" << authorization.artifactSetSha256 << "\n"
                   << "releaseVersion=" << authorization.releaseVersion << "\n"
                   << "gitCommit=" << authorization.gitCommit << "\n"
                   << "builderId=" << authorization.builderId << "\n"
                   << "buildProfile=" << authorization.buildProfile << "\n";
            stream.close();
        }
        Poco::File targetFile(target);
        if (targetFile.exists()) targetFile.remove();
        Poco::File(temporary).renameTo(target.toString());
    }

    static void copyRepositoryExactly(const std::string& sourceDirectory,
                                      const std::string& targetDirectory)
    {
        namespace fs = std::filesystem;
        const fs::path source = fs::u8path(sourceDirectory);
        const fs::path target = fs::u8path(targetDirectory);
        for (const auto& entry : fs::directory_iterator(source))
        {
            fs::copy(entry.path(), target / entry.path().filename(),
                     fs::copy_options::recursive |
                         fs::copy_options::copy_symlinks |
                         fs::copy_options::overwrite_existing);
        }
    }

    void commitBackup(const Poco::OSP::BundleRepository::Bundles& candidates,
                      const std::string& candidateDigest,
                      const BundleRepositoryAuthorizationEvidence& authorization)
    {
        recoverBackupSwap();
        Poco::File staging(stagingPath());
        staging.createDirectories();

        std::size_t index = 0;
        try
        {
            const std::string literalRepository = repositoryDirectory();
            if (!literalRepository.empty())
            {
                copyRepositoryExactly(literalRepository, staging.path());
            }
            else
            {
                for (const auto& candidate : candidates)
                {
                    Poco::Path source(candidate->path());
                    std::string fileName = source.getFileName();
                    if (fileName.empty())
                        fileName = candidate->symbolicName() + "_" + candidate->version().toString() + ".bndl";
                    Poco::Path destination(staging.path());
                    destination.makeDirectory();
                    destination.setFileName(Poco::NumberFormatter::format0(index++, 4) + "_" + fileName);
                    Poco::File(candidate->path()).copyTo(destination.toString());
                }
            }

            Poco::File active(backupPath());
            Poco::File previous(previousPath());
            const std::string activePath = active.path();
            if (active.exists())
                active.renameTo(previous.path());
            staging.renameTo(activePath);
            if (previous.exists())
                previous.remove(true);
            writeBackupMetadata(candidateDigest, authorization);
        }
        catch (...)
        {
            recoverBackupSwap();
            throw;
        }
    }

    void restoreBackup()
    {
        if (!backupAvailable())
            throw Poco::FileNotFoundException("No last-known-good Bundle repository backup", backupPath().toString());
        Poco::OSP::BundleRepository repository(backupPath().toString(), _osp.bundleLoader(),
                                               _osp.getBundleFilter());
        const Poco::OSP::BundleRepository::Bundles candidates = repository.validateBundles();
        activate(candidates);
    }

    void handleFailure(const std::string& transactionId, bool runtimeTouched,
                       const std::string& error)
    {
        ++_failedReloads;
        setError(error);
        if (!runtimeTouched)
        {
            ++_rejectedReloads;
            writeJournal(transactionId, "rejected", 0, error);
            appendAudit(transactionId, "rejected", 0, error);
            _logger.error("Bundle repository transaction %s rejected before runtime mutation: %s",
                          transactionId, error);
            return;
        }

        try
        {
            restoreBackup();
            ++_rolledBackReloads;
            writeJournal(transactionId, "rolledBack", 0, error);
            appendAudit(transactionId, "rolledBack", 0, error);
            _logger.error("Bundle repository transaction %s failed and was rolled back: %s",
                          transactionId, error);
        }
        catch (const Poco::Exception& rollbackError)
        {
            const std::string combined = error + "; rollback failed: " + rollbackError.displayText();
            setError(combined);
            writeJournal(transactionId, "rollbackFailed", 0, combined);
            appendAudit(transactionId, "rollbackFailed", 0, combined);
            _logger.fatal("Bundle repository transaction %s and rollback both failed: %s",
                          transactionId, combined);
        }
    }

    void writeJournal(const std::string& transactionId, const std::string& state,
                      std::size_t bundleCount, const std::string& error,
                      const std::string& candidateDigest = std::string(),
                      const BundleRepositoryAuthorizationEvidence& authorization = {}) const
    {
        ensureStateDirectory();
        const Poco::Path target = statePath("transaction.properties");
        const Poco::Path temporary = statePath("transaction.properties.tmp");
        {
            Poco::FileOutputStream stream(temporary.toString(), std::ios::out | std::ios::trunc);
            if (!stream.good())
                throw Poco::CreateFileException(temporary.toString());
            stream << "transactionId=" << transactionId << "\n"
                   << "state=" << state << "\n"
                   << "bundleCount=" << bundleCount << "\n"
                   << "candidateDigest=" << candidateDigest << "\n"
                   << "authorizationVerified=" << (authorization.verified ? "true" : "false") << "\n"
                   << "repositoryId=" << authorization.repositoryId << "\n"
                   << "publisherId=" << authorization.publisherId << "\n"
                   << "signingKeyId=" << authorization.keyId << "\n"
                   << "trustPolicyId=" << authorization.policyId << "\n"
                   << "trustPolicySha256=" << authorization.policySha256 << "\n"
                   << "attestationSha256=" << authorization.attestationSha256 << "\n"
                   << "rolloutSequence=" << authorization.rolloutSequence << "\n"
                   << "releaseManifestSha256=" << authorization.releaseManifestSha256 << "\n"
                   << "sbomSha256=" << authorization.sbomSha256 << "\n"
                   << "artifactSetSha256=" << authorization.artifactSetSha256 << "\n"
                   << "releaseVersion=" << authorization.releaseVersion << "\n"
                   << "gitCommit=" << authorization.gitCommit << "\n"
                   << "builderId=" << authorization.builderId << "\n"
                   << "buildProfile=" << authorization.buildProfile << "\n"
                   << "timestamp=" << Poco::DateTimeFormatter::format(Poco::Timestamp(),
                                                                         Poco::DateTimeFormat::ISO8601_FRAC_FORMAT)
                   << "\n"
                   << "error=" << error << "\n";
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
        throw Poco::FileException("Cannot replace Bundle transaction journal: " + lastError,
                                  target.toString());
    }

    void appendAudit(const std::string& transactionId, const std::string& state,
                     std::size_t bundleCount, const std::string& error,
                     const std::string& candidateDigest = std::string(),
                     const BundleRepositoryAuthorizationEvidence& authorization = {}) const
    {
        ensureStateDirectory();
        Poco::FileOutputStream stream(statePath("transactions.jsonl").toString(),
                                      std::ios::out | std::ios::app);
        if (!stream.good())
            throw Poco::CreateFileException(statePath("transactions.jsonl").toString());
        stream << "{\"timestamp\":\""
               << jsonEscape(Poco::DateTimeFormatter::format(Poco::Timestamp(),
                                                              Poco::DateTimeFormat::ISO8601_FRAC_FORMAT))
               << "\",\"transactionId\":\"" << jsonEscape(transactionId)
               << "\",\"state\":\"" << jsonEscape(state)
               << "\",\"bundleCount\":" << bundleCount
               << ",\"candidateDigest\":\"" << jsonEscape(candidateDigest)
               << "\",\"authorizationVerified\":" << (authorization.verified ? "true" : "false")
               << ",\"repositoryId\":\"" << jsonEscape(authorization.repositoryId)
               << "\",\"publisherId\":\"" << jsonEscape(authorization.publisherId)
               << "\",\"signingKeyId\":\"" << jsonEscape(authorization.keyId)
               << "\",\"trustPolicyId\":\"" << jsonEscape(authorization.policyId)
               << "\",\"trustPolicySha256\":\"" << jsonEscape(authorization.policySha256)
               << "\",\"attestationSha256\":\"" << jsonEscape(authorization.attestationSha256)
               << "\",\"rolloutSequence\":" << authorization.rolloutSequence
               << ",\"releaseManifestSha256\":\"" << jsonEscape(authorization.releaseManifestSha256)
               << "\",\"sbomSha256\":\"" << jsonEscape(authorization.sbomSha256)
               << "\",\"artifactSetSha256\":\"" << jsonEscape(authorization.artifactSetSha256)
               << "\",\"releaseVersion\":\"" << jsonEscape(authorization.releaseVersion)
               << "\",\"gitCommit\":\"" << jsonEscape(authorization.gitCommit)
               << "\",\"builderId\":\"" << jsonEscape(authorization.builderId)
               << "\",\"buildProfile\":\"" << jsonEscape(authorization.buildProfile)
               << "\",\"error\":\"" << jsonEscape(error) << "\"}\n";
    }

    void setError(const std::string& error)
    {
        std::lock_guard<std::mutex> guard(_errorMutex);
        _lastError = error;
    }

    void clearError() { setError(std::string()); }

    void addPath(const std::string& path, Snapshot& snapshot) const
    {
        Poco::File file(path);
        if (!file.exists())
            return;

        Poco::Path normalized(path);
        normalized.makeAbsolute();
        snapshot[normalized.toString()] = {file.getLastModified().epochMicroseconds(),
                                           file.isFile() ? file.getSize() : 0};
        if (!file.isDirectory())
            return;

        for (Poco::DirectoryIterator iterator(path), end; iterator != end; ++iterator)
        {
            if (!iterator->isHidden())
                addPath(iterator->path(), snapshot);
        }
    }

    Snapshot scan() const
    {
#if defined(POCO_OS_FAMILY_UNIX)
        const std::string separators(":;");
#else
        const std::string separators(";");
#endif
        Poco::StringTokenizer paths(_options.repositories, separators,
                                    Poco::StringTokenizer::TOK_IGNORE_EMPTY |
                                        Poco::StringTokenizer::TOK_TRIM);
        Snapshot snapshot;
        for (const auto& path : paths)
        {
            Poco::File literal(path);
            if (literal.exists())
            {
                addPath(path, snapshot);
                continue;
            }

            std::set<std::string> matches;
#if defined(POCO_OS_FAMILY_WINDOWS)
            Poco::Glob::glob(path, matches, Poco::Glob::GLOB_CASELESS);
#else
            Poco::Glob::glob(path, matches, Poco::Glob::GLOB_DEFAULT);
#endif
            for (const auto& match : matches)
                addPath(match, snapshot);
        }
        return snapshot;
    }

    void monitor()
    {
        Snapshot applied = scan();
        Snapshot rejected;
        Snapshot pending;
        std::size_t stableScans = 0;

        while (!_stop.tryWait(static_cast<long>(_options.intervalMilliseconds)))
        {
            try
            {
                Snapshot current = scan();
                if (current == applied)
                {
                    stableScans = 0;
                    pending.clear();
                    continue;
                }
                if (!rejected.empty() && current == rejected)
                {
                    stableScans = 0;
                    pending.clear();
                    continue;
                }
                if (stableScans == 0 || current != pending)
                {
                    pending = std::move(current);
                    stableScans = 1;
                    continue;
                }
                ++stableScans;
                if (stableScans < _options.stableScanCount)
                    continue;

                reload();
                applied = std::move(current);
                rejected.clear();
                pending.clear();
                stableScans = 0;
            }
            catch (const Poco::Exception& exception)
            {
                rejected = scan();
                _logger.error("Bundle repository reload failed: %s", exception.displayText());
            }
            catch (const std::exception& exception)
            {
                rejected = scan();
                _logger.error("Bundle repository reload failed: %s",
                              std::string(exception.what()));
            }
        }
    }

    Poco::OSP::OSPSubsystem& _osp;
    Poco::Logger& _logger;
    BundleManagerOptions _options;
    Poco::Event _stop;
    std::thread _worker;
    std::mutex _reloadMutex;
    mutable std::mutex _errorMutex;
    std::string _lastError;
    std::atomic<bool> _running{false};
    std::atomic<std::size_t> _successfulReloads{0};
    std::atomic<std::size_t> _failedReloads{0};
    std::atomic<std::size_t> _rejectedReloads{0};
    std::atomic<std::size_t> _rolledBackReloads{0};
    std::atomic<std::size_t> _restartRequiredReloads{0};
};

BundleManager::BundleManager(Poco::OSP::OSPSubsystem& osp, Poco::Logger& logger,
                             BundleManagerOptions options)
    : _impl(new Impl(osp, logger, std::move(options)))
{
}

BundleManager::~BundleManager() { delete _impl; }
void BundleManager::start() { _impl->start(); }
void BundleManager::stop() { _impl->stop(); }
void BundleManager::reloadNow() { _impl->reload(); }
bool BundleManager::running() const { return _impl->running(); }
std::size_t BundleManager::successfulReloads() const { return _impl->successfulReloads(); }
std::size_t BundleManager::failedReloads() const { return _impl->failedReloads(); }
std::size_t BundleManager::rejectedReloads() const { return _impl->rejectedReloads(); }
std::size_t BundleManager::rolledBackReloads() const { return _impl->rolledBackReloads(); }
std::size_t BundleManager::restartRequiredReloads() const
{
    return _impl->restartRequiredReloads();
}
std::string BundleManager::lastError() const { return _impl->lastError(); }
} // namespace PocoDDS::BundleManagement
