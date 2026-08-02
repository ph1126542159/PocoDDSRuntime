#include "Poco/ClassLibrary.h"
#include "Poco/AutoPtr.h"
#include "Poco/Environment.h"
#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/DirectoryIterator.h"
#include "Poco/JSON/Array.h"
#include "Poco/JSON/Object.h"
#include "Poco/JSON/Parser.h"
#include "Poco/Net/HTTPServerRequest.h"
#include "Poco/Net/HTTPServerResponse.h"
#include "Poco/Net/HTTPRequestHandler.h"
#include "Poco/OSP/BundleActivator.h"
#include "Poco/OSP/BundleContext.h"
#include "Poco/OSP/BundleEvent.h"
#include "Poco/OSP/BundleEvents.h"
#include "Poco/OSP/Properties.h"
#include "Poco/OSP/PreferencesService.h"
#include "Poco/OSP/ServiceFinder.h"
#include "Poco/OSP/Service.h"
#include "Poco/OSP/ServiceListener.h"
#include "Poco/OSP/ServiceRef.h"
#include "Poco/OSP/ServiceRegistry.h"
#include "Poco/OSP/Web/WebRequestHandlerFactory.h"
#include "Poco/NumberParser.h"
#include "Poco/Path.h"
#include "Poco/Process.h"
#include "Poco/SHA2Engine.h"
#include "Poco/DigestEngine.h"
#include "Poco/Runnable.h"
#include "Poco/Thread.h"
#include "Poco/Timestamp.h"
#include "Poco/Timespan.h"
#include "Poco/Mutex.h"
#include "Poco/URI.h"
#include "Poco/UnicodeConverter.h"
#include "Poco/Util/AbstractConfiguration.h"
#include "Poco/Util/Application.h"
#include "Poco/Util/MapConfiguration.h"
#include "Poco/Util/PropertyFileConfiguration.h"
#include "PocoDDS/Configuration/ConfigurationValidator.h"
#include "Poco/Delegate.h"
#include "PocoDDS/Observability/TraceStore.h"
#include "PocoDDS/Observability/Metrics.h"
#include "PocoDDS/Health/Health.h"
#include "PocoDDS/ProcessManagement/SubprocessManager.h"
#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/Devices/DeviceService.h"
#include "PocoDDS/Protocols/ProtocolService.h"
#include "PocoDDS/Reliability/AlertSink.h"
#include "PocoDDS/ManagementAuth/IdentityService.h"
#include "PocoDDS/Security/PrincipalStore.h"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstdint>
#include <chrono>
#include <deque>
#include <fstream>
#include <functional>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <memory>
#include <condition_variable>
#include <cstdio>
#include <regex>

#if defined(POCO_OS_FAMILY_WINDOWS)
#include <Windows.h>
#include <Iphlpapi.h>
#include <Psapi.h>
#include <TlHelp32.h>
#elif defined(POCO_OS_FAMILY_UNIX)
#include <sys/sysinfo.h>
#include <unistd.h>
#endif

namespace PocoDDS::SystemMonitoring
{
namespace
{
constexpr const char* SERVICE_NAME = "pdr.platform.systemMonitoring";
constexpr const char* DEFAULT_MANAGEABLE_BUNDLES =
    "pdr.service.*,pdr.device.*,pdr.alert.*,pdr.plugin.*";

void appendPluginQuarantineGovernance(const std::string& id,
                                      Poco::JSON::Object::Ptr target);
bool pluginQuarantineBlocks(const std::string& id);

std::string sha256Digest(const std::string& value)
{
    Poco::SHA2Engine sha256(Poco::SHA2Engine::SHA_256);
    sha256.update(value);
    return Poco::DigestEngine::digestToHex(sha256.digest());
}

std::mutex& bundleManagementMutex()
{
    static std::mutex mutex;
    return mutex;
}

std::vector<std::string>& manageableBundlePatterns()
{
    static std::vector<std::string> patterns{
        "pdr.service.*", "pdr.device.*", "pdr.alert.*"};
    return patterns;
}

bool protectedBundle(const std::string& id)
{
    return id.rfind("osp.", 0) == 0 || id.rfind("com.appinf.osp.", 0) == 0 ||
        id.rfind("poco.", 0) == 0 || id.rfind("pdr.platform.", 0) == 0 ||
        id.rfind("pdr.webui.", 0) == 0;
}

void configureManageableBundles(const std::string& configured)
{
    std::vector<std::string> patterns;
    std::istringstream stream(configured);
    std::string pattern;
    while (std::getline(stream, pattern, ','))
    {
        pattern.erase(0, pattern.find_first_not_of(" \t"));
        const auto end = pattern.find_last_not_of(" \t");
        if (end != std::string::npos) pattern.erase(end + 1);
        if (!pattern.empty()) patterns.push_back(std::move(pattern));
    }
    std::lock_guard<std::mutex> lock(bundleManagementMutex());
    manageableBundlePatterns() = std::move(patterns);
}

bool manageableBundle(const std::string& id)
{
    if (protectedBundle(id)) return false;
    std::lock_guard<std::mutex> lock(bundleManagementMutex());
    return std::any_of(manageableBundlePatterns().begin(), manageableBundlePatterns().end(),
        [&id](const std::string& pattern) {
            return pattern.back() == '*'
                ? id.rfind(pattern.substr(0, pattern.size() - 1), 0) == 0
                : id == pattern;
        });
}

bool appendBundleGovernance(Poco::OSP::BundleContext::Ptr context,
                            const Poco::OSP::Bundle::Ptr& bundle,
                            Poco::JSON::Object::Ptr target)
{
    const std::string id = bundle->symbolicName();
    const bool plugin = id.rfind("pdr.plugin.", 0) == 0;
    const bool protectedInfrastructure = protectedBundle(id);
    bool compatible = true;
    Poco::JSON::Array::Ptr compatibilityIssues = new Poco::JSON::Array;
    if (plugin)
    {
        const auto& manifest = bundle->manifest().rawManifest();
        const std::string api = manifest.getString("PDR-Plugin-API", "");
        const std::string abi = manifest.getString("PDR-Plugin-ABI", "");
        const std::string fingerprint =
            manifest.getString("PDR-Plugin-ABI-Fingerprint", "");
        const std::string runtimeRange = manifest.getString("PDR-Runtime-Version", "");
        target->set("pluginApiVersion", api);
        target->set("pluginAbiVersion", abi);
        target->set("pluginAbiFingerprint", fingerprint);
        target->set("runtimeVersionRange", runtimeRange);
        auto requireEqual = [&](const std::string& name, const std::string& actual,
                                const std::string& expected)
        {
            if (actual != expected)
            {
                compatible = false;
                compatibilityIssues->add(name + (actual.empty() ? " is missing" : " mismatch"));
            }
        };
        requireEqual("plugin API", api, PDR_PLUGIN_API_VERSION);
        requireEqual("plugin ABI", abi, PDR_PLUGIN_ABI_VERSION);
        requireEqual("plugin ABI fingerprint", fingerprint, PDR_PLUGIN_ABI_FINGERPRINT);
        try
        {
            const auto comma = runtimeRange.find(',');
            const bool rangeSyntax = runtimeRange.size() >= 5 &&
                (runtimeRange.front() == '[' || runtimeRange.front() == '(') &&
                (runtimeRange.back() == ']' || runtimeRange.back() == ')') &&
                comma != std::string::npos;
            if (!rangeSyntax) throw Poco::InvalidArgumentException("invalid version range");
            std::string lowerText = runtimeRange.substr(1, comma - 1);
            std::string upperText = runtimeRange.substr(
                comma + 1, runtimeRange.size() - comma - 2);
            Poco::trimInPlace(lowerText);
            Poco::trimInPlace(upperText);
            if (lowerText.empty() || upperText.empty())
                throw Poco::InvalidArgumentException("open version ranges are not supported");
            const Poco::OSP::VersionRange requestedRuntime(
                Poco::OSP::Version(lowerText), runtimeRange.front() == '[',
                Poco::OSP::Version(upperText), runtimeRange.back() == ']');
            if (!requestedRuntime.isInRange(Poco::OSP::Version(PDR_RUNTIME_VERSION)))
            {
                compatible = false;
                compatibilityIssues->add(runtimeRange.empty()
                    ? "Runtime version range is missing" : "Runtime version mismatch");
            }
        }
        catch (const Poco::Exception&)
        {
            compatible = false;
            compatibilityIssues->add("Runtime version range is invalid");
        }
    }
    target->set("compatibilityIssues", compatibilityIssues);
    appendPluginQuarantineGovernance(id, target);
    Poco::JSON::Array::Ptr dependencies = new Poco::JSON::Array;
    for (const auto& dependency : bundle->requiredBundles())
    {
        Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
        item->set("id", dependency.symbolicName);
        const std::string requested = dependency.versions.toString();
        item->set("requestedVersion", requested.empty() ? "*" : requested);
        const auto available = context->findBundle(dependency.symbolicName);
        const bool versionCompatible = available &&
            (dependency.versions.isEmpty() ||
             dependency.versions.isInRange(available->version()));
        item->set("available", static_cast<bool>(available));
        item->set("compatible", versionCompatible);
        if (available)
        {
            item->set("availableVersion", available->version().toString());
            item->set("state", available->stateString());
        }
        else
        {
            item->set("availableVersion", "");
            item->set("state", "missing");
        }
        compatible = compatible && versionCompatible;
        dependencies->add(item);
    }
    target->set("plugin", plugin);
    target->set("protected", protectedInfrastructure);
    target->set("compatible", compatible);
    target->set("dependencies", dependencies);
    target->set("governanceStatus", pluginQuarantineBlocks(id) ? "quarantined" :
        !compatible ? "incompatible" :
        protectedInfrastructure ? "protected" :
        manageableBundle(id) ? "ready" : "unmanaged");
    return compatible;
}

bool editableConfiguration(const std::string& key)
{
    return key == "logging.loggers.root.level" ||
        key.rfind("deviceStatus.", 0) == 0 ||
        key.rfind("mobile.", 0) == 0 ||
        key.rfind("pdr.modbus.", 0) == 0 ||
        key.rfind("pdr.serial.", 0) == 0 ||
        key.rfind("pdr.gnss.", 0) == 0 ||
        key.rfind("pdr.gpio.", 0) == 0 ||
        key.rfind("pdr.xbee.", 0) == 0 ||
        key.rfind("pdr.can.", 0) == 0 ||
        key.rfind("pdr.led.", 0) == 0;
}

std::string configurationOwner(const std::string& key)
{
    if (key.rfind("deviceStatus.", 0) == 0) return "pdr.service.deviceStatus";
    if (key.rfind("mobile.", 0) == 0) return "pdr.service.mobile";
    if (key.rfind("pdr.", 0) == 0) return "pdr.device.gateway";
    return {};
}

struct ManagementAuthorization
{
    bool required{false};
    bool requireRequestId{false};
    bool auditEnabled{true};
    Poco::Path auditPath;
    Poco::File::FileSize auditMaximumBytes{4 * 1024 * 1024};
    PocoDDS::ManagementAuth::IdentityService::Ptr identityService;
};

ManagementAuthorization& managementAuthorization()
{
    static ManagementAuthorization authorization;
    return authorization;
}

void configureManagementAuthorization(const Poco::Util::AbstractConfiguration& config,
                                      Poco::OSP::BundleContext::Ptr context)
{
    ManagementAuthorization configured;
    const auto identityRef = context->registry().findByName(
        PocoDDS::ManagementAuth::IdentityService::SERVICE_NAME);
    configured.identityService =
        identityRef->castedInstance<PocoDDS::ManagementAuth::IdentityService>();
    configured.required = configured.identityService->snapshot().required;
    configured.requireRequestId =
        config.getBool("pdr.management.idempotency.requireRequestId", false);
    configured.auditEnabled = config.getBool("pdr.management.audit.enabled", true);
    configured.auditPath = Poco::Path(config.getString(
        "pdr.management.audit.path", "management-audit.jsonl"));
    configured.auditPath.makeAbsolute();
    configured.auditMaximumBytes = static_cast<Poco::File::FileSize>(config.getUInt64(
        "pdr.management.audit.maximumBytes", 4 * 1024 * 1024));
    managementAuthorization() = std::move(configured);
}

std::mutex& configurationUpdateMutex()
{
    static std::mutex mutex;
    return mutex;
}

void copyConfiguration(const Poco::Util::AbstractConfiguration& source,
                       Poco::Util::AbstractConfiguration& destination,
                       const std::string& prefix = {})
{
    Poco::Util::AbstractConfiguration::Keys keys;
    source.keys(prefix, keys);
    for (const auto& key : keys)
    {
        const std::string fullKey = prefix.empty() ? key : prefix + "." + key;
        Poco::Util::AbstractConfiguration::Keys children;
        source.keys(fullKey, children);
        if (!children.empty()) copyConfiguration(source, destination, fullKey);
        else destination.setString(fullKey, source.getRawString(fullKey, ""));
    }
}

void replaceConfigurationFile(const Poco::Path& source, const Poco::Path& destination)
{
#if defined(POCO_OS_FAMILY_WINDOWS)
    std::wstring wideSource;
    std::wstring wideDestination;
    Poco::UnicodeConverter::toUTF16(source.toString(), wideSource);
    Poco::UnicodeConverter::toUTF16(destination.toString(), wideDestination);
    for (int attempt = 0; attempt < 20; ++attempt)
    {
        if (MoveFileExW(wideSource.c_str(), wideDestination.c_str(),
                        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) return;
        const DWORD error = GetLastError();
        if (attempt == 19 || (error != ERROR_SHARING_VIOLATION &&
                              error != ERROR_LOCK_VIOLATION && error != ERROR_ACCESS_DENIED))
            throw Poco::FileException("cannot replace runtime configuration",
                                      destination.toString() + " (Windows error " +
                                          std::to_string(error) + ")");
        Poco::Thread::sleep(25);
    }
#else
    if (std::rename(source.toString().c_str(), destination.toString().c_str()) != 0)
        throw Poco::FileException("cannot replace runtime configuration", destination.toString());
#endif
}

Poco::JSON::Object::Ptr readJsonObject(const Poco::Path& path)
{
    if (!Poco::File(path).exists()) return nullptr;
    Poco::FileInputStream stream(path.toString());
    return Poco::JSON::Parser().parse(stream).extract<Poco::JSON::Object::Ptr>();
}

void validatePersistenceSnapshot(const Poco::Path& path, const std::string& arrayField)
{
    auto root = readJsonObject(path);
    if (!root) throw Poco::FileNotFoundException(path.toString());
    const int schemaVersion = root->optValue<int>("schemaVersion", 0);
    if (schemaVersion != 1 && schemaVersion != 2)
        throw Poco::DataFormatException("unsupported persistence snapshot schema");
    auto records = root->getArray(arrayField);
    if (!records)
        throw Poco::DataFormatException(
            "persistence snapshot is missing " + arrayField + " array");
    if (schemaVersion == 2)
    {
        std::ostringstream serializedRecords;
        records->stringify(serializedRecords);
        if (root->optValue<std::string>("contentSha256", "") !=
            sha256Digest(serializedRecords.str()))
            throw Poco::DataFormatException("persistence snapshot integrity check failed");
    }
}

void preservePreviousSnapshot(const Poco::Path& current, const std::string& arrayField)
{
    if (!Poco::File(current).exists()) return;
    validatePersistenceSnapshot(current, arrayField);
    Poco::Path stagedPrevious(current.toString() + ".previous.new");
    Poco::Path previous(current.toString() + ".previous");
    if (Poco::File(stagedPrevious).exists()) Poco::File(stagedPrevious).remove();
    Poco::File(current).copyTo(stagedPrevious.toString());
    validatePersistenceSnapshot(stagedPrevious, arrayField);
    replaceConfigurationFile(stagedPrevious, previous);
}

bool verifiedPreviousSnapshotAvailable(const Poco::Path& current,
                                       const std::string& arrayField)
{
    try
    {
        Poco::Path previous(current.toString() + ".previous");
        if (!Poco::File(previous).exists()) return false;
        validatePersistenceSnapshot(previous, arrayField);
        return true;
    }
    catch (...) { return false; }
}

void stageJsonObject(const Poco::JSON::Object& object, const Poco::Path& path)
{
    if (Poco::File(path).exists()) Poco::File(path).remove();
    Poco::FileOutputStream stream(path.toString());
    object.stringify(stream);
    stream.close();
    if (!stream.good()) throw Poco::WriteFileException(path.toString());
    (void) readJsonObject(path);
}

struct PluginQuarantineRecord
{
    std::uint64_t totalFailures{0};
    std::uint64_t consecutiveFailures{0};
    bool quarantined{false};
    Poco::Int64 updatedMicroseconds{0};
    std::string lastError;
};

class PluginQuarantineManager
{
public:
    void configure(const Poco::Util::AbstractConfiguration& config,
                   Poco::OSP::BundleContext::Ptr context)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _enabled = config.getBool("pdr.plugins.quarantine.enabled", true);
        _threshold = static_cast<std::uint64_t>(std::max(1,
            config.getInt("pdr.plugins.quarantine.failureThreshold", 3)));
        _path = Poco::Path(config.expand(config.getString(
            "pdr.plugins.quarantine.path",
            "${application.dir}data/plugin-quarantine.json"))).makeAbsolute();
        _records.clear();
        _recoveryRequired = false;
        _lastPersistenceError.clear();
        if (_enabled && Poco::File(_path).exists())
        {
            try
            {
                auto root = readJsonObject(_path);
                if (!root || root->optValue<int>("schemaVersion", 0) != 2)
                    throw Poco::DataFormatException("unsupported plugin quarantine schema");
                auto records = root->getArray("plugins");
                if (!records) throw Poco::DataFormatException(
                    "plugin quarantine snapshot is missing plugins array");
                std::ostringstream serialized;
                records->stringify(serialized);
                if (root->optValue<std::string>("contentSha256", "") !=
                    sha256Digest(serialized.str()))
                    throw Poco::DataFormatException(
                        "plugin quarantine snapshot integrity check failed");
                for (std::size_t index = 0; index < records->size(); ++index)
                {
                    auto item = records->getObject(static_cast<unsigned>(index));
                    const std::string id = item->getValue<std::string>("id");
                    if (id.rfind("pdr.plugin.", 0) != 0 || _records.count(id))
                        throw Poco::DataFormatException(
                            "plugin quarantine snapshot contains an invalid or duplicate id");
                    PluginQuarantineRecord record;
                    record.totalFailures = item->optValue<Poco::UInt64>("totalFailures", 0);
                    record.consecutiveFailures =
                        item->optValue<Poco::UInt64>("consecutiveFailures", 0);
                    record.quarantined = item->optValue<bool>("quarantined", false);
                    record.updatedMicroseconds =
                        item->optValue<Poco::Int64>("updatedMicroseconds", 0);
                    record.lastError = item->optValue<std::string>("lastError", "");
                    _records.emplace(id, std::move(record));
                }
            }
            catch (const std::exception& exception)
            {
                _recoveryRequired = true;
                _lastPersistenceError = exception.what();
            }
        }
        std::vector<Poco::OSP::Bundle::Ptr> bundles;
        context->listBundles(bundles);
        for (auto bundle : bundles)
        {
            if (bundle->symbolicName().rfind("pdr.plugin.", 0) != 0) continue;
            const auto iterator = _records.find(bundle->symbolicName());
            bundle->setAutoStartBlocked(_enabled && (_recoveryRequired ||
                (iterator != _records.end() && iterator->second.quarantined)));
        }
    }

    bool blocked(const std::string& id) const
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (!_enabled || id.rfind("pdr.plugin.", 0) != 0) return false;
        const auto iterator = _records.find(id);
        return _recoveryRequired ||
            (iterator != _records.end() && iterator->second.quarantined);
    }

    void append(const std::string& id, Poco::JSON::Object::Ptr target) const
    {
        if (id.rfind("pdr.plugin.", 0) != 0) return;
        std::lock_guard<std::mutex> lock(_mutex);
        const auto iterator = _records.find(id);
        const PluginQuarantineRecord empty;
        const auto& record = iterator == _records.end() ? empty : iterator->second;
        target->set("quarantined", _enabled && (_recoveryRequired || record.quarantined));
        target->set("quarantineFailureThreshold", static_cast<Poco::UInt64>(_threshold));
        target->set("quarantineTotalFailures", static_cast<Poco::UInt64>(record.totalFailures));
        target->set("quarantineConsecutiveFailures",
                    static_cast<Poco::UInt64>(record.consecutiveFailures));
        target->set("quarantineUpdatedMicroseconds", record.updatedMicroseconds);
        target->set("quarantineLastError", record.lastError);
        target->set("quarantinePersistenceHealthy", !_recoveryRequired &&
                    _lastPersistenceError.empty());
        target->set("quarantineRecoveryRequired", _recoveryRequired);
        if (!_lastPersistenceError.empty())
            target->set("quarantinePersistenceError", _lastPersistenceError);
    }

    void failure(Poco::OSP::Bundle::Ptr bundle, const std::string& error)
    {
        if (!_enabled || bundle->symbolicName().rfind("pdr.plugin.", 0) != 0) return;
        std::lock_guard<std::mutex> lock(_mutex);
        auto& record = _records[bundle->symbolicName()];
        ++record.totalFailures;
        ++record.consecutiveFailures;
        record.lastError = error;
        record.updatedMicroseconds = Poco::Timestamp().epochMicroseconds();
        if (record.consecutiveFailures >= _threshold) record.quarantined = true;
        bundle->setAutoStartBlocked(record.quarantined || _recoveryRequired);
        persistNoThrowLocked();
        bundle->setAutoStartBlocked(record.quarantined || _recoveryRequired);
    }

    void success(Poco::OSP::Bundle::Ptr bundle)
    {
        if (!_enabled || bundle->symbolicName().rfind("pdr.plugin.", 0) != 0) return;
        std::lock_guard<std::mutex> lock(_mutex);
        auto iterator = _records.find(bundle->symbolicName());
        if (iterator == _records.end() || iterator->second.consecutiveFailures == 0) return;
        iterator->second.consecutiveFailures = 0;
        iterator->second.updatedMicroseconds = Poco::Timestamp().epochMicroseconds();
        persistNoThrowLocked();
    }

    void reset(Poco::OSP::Bundle::Ptr bundle, bool confirmRecovery)
    {
        if (bundle->symbolicName().rfind("pdr.plugin.", 0) != 0)
            throw Poco::InvalidArgumentException("only external plugins have quarantine state");
        std::lock_guard<std::mutex> lock(_mutex);
        if (_recoveryRequired && !confirmRecovery)
            throw Poco::IllegalStateException(
                "plugin quarantine persistence requires explicit recovery confirmation");
        if (_recoveryRequired)
        {
            _records.clear();
            _recoveryRequired = false;
            _lastPersistenceError.clear();
        }
        _records.erase(bundle->symbolicName());
        persistLocked();
        bundle->setAutoStartBlocked(false);
    }

private:
    void persistLocked()
    {
        if (!_enabled) return;
        if (_recoveryRequired)
            throw Poco::IllegalStateException(
                "plugin quarantine persistence requires operator recovery");
        Poco::JSON::Array::Ptr records = new Poco::JSON::Array;
        std::vector<std::string> ids;
        ids.reserve(_records.size());
        for (const auto& entry : _records) ids.push_back(entry.first);
        std::sort(ids.begin(), ids.end());
        for (const auto& id : ids)
        {
            const auto& record = _records.at(id);
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("id", id);
            item->set("totalFailures", static_cast<Poco::UInt64>(record.totalFailures));
            item->set("consecutiveFailures",
                      static_cast<Poco::UInt64>(record.consecutiveFailures));
            item->set("quarantined", record.quarantined);
            item->set("updatedMicroseconds", record.updatedMicroseconds);
            item->set("lastError", record.lastError);
            records->add(item);
        }
        std::ostringstream serialized;
        records->stringify(serialized);
        Poco::JSON::Object root;
        root.set("schemaVersion", 2);
        root.set("savedAtMicroseconds", Poco::Timestamp().epochMicroseconds());
        root.set("contentSha256", sha256Digest(serialized.str()));
        root.set("plugins", records);
        Poco::File parent(_path.parent());
        if (!parent.exists()) parent.createDirectories();
        Poco::Path staged(_path.toString() + ".new");
        stageJsonObject(root, staged);
        replaceConfigurationFile(staged, _path);
        _lastPersistenceError.clear();
    }

    void persistNoThrowLocked()
    {
        try { persistLocked(); }
        catch (const std::exception& exception)
        {
            _lastPersistenceError = exception.what();
            _recoveryRequired = true;
        }
    }

    mutable std::mutex _mutex;
    std::unordered_map<std::string, PluginQuarantineRecord> _records;
    Poco::Path _path;
    std::uint64_t _threshold{3};
    bool _enabled{true};
    bool _recoveryRequired{false};
    std::string _lastPersistenceError;
};

PluginQuarantineManager& pluginQuarantineManager()
{
    static PluginQuarantineManager manager;
    return manager;
}

void appendPluginQuarantineGovernance(const std::string& id,
                                      Poco::JSON::Object::Ptr target)
{
    pluginQuarantineManager().append(id, target);
}

bool pluginQuarantineBlocks(const std::string& id)
{
    return pluginQuarantineManager().blocked(id);
}

void appendConfigurationAudit(const Poco::Path& runtimePath,
                              const Poco::JSON::Object& record)
{
    const Poco::Path auditPath(runtimePath.toString() + ".audit.jsonl");
    constexpr Poco::File::FileSize MAXIMUM_AUDIT_BYTES = 4 * 1024 * 1024;
    if (Poco::File(auditPath).exists() &&
        Poco::File(auditPath).getSize() >= MAXIMUM_AUDIT_BYTES)
    {
        const Poco::Path archivePath(auditPath.toString() + ".1");
        if (Poco::File(archivePath).exists()) Poco::File(archivePath).remove();
        Poco::File(auditPath).renameTo(archivePath.toString());
    }
    Poco::FileOutputStream stream(auditPath.toString(), std::ios::app);
    record.stringify(stream);
    stream << '\n';
    stream.close();
    if (!stream.good()) throw Poco::WriteFileException(auditPath.toString());
}

Poco::JSON::Array::Ptr recentConfigurationAudit(const Poco::Path& runtimePath,
                                                std::size_t limit)
{
    Poco::JSON::Array::Ptr records = new Poco::JSON::Array;
    const Poco::Path auditPath(runtimePath.toString() + ".audit.jsonl");
    if (!Poco::File(auditPath).exists()) return records;
    std::ifstream stream(auditPath.toString());
    std::deque<Poco::JSON::Object::Ptr> tail;
    std::string line;
    while (std::getline(stream, line))
    {
        try
        {
            tail.push_back(Poco::JSON::Parser().parse(line)
                               .extract<Poco::JSON::Object::Ptr>());
            if (tail.size() > limit) tail.pop_front();
        }
        catch (...) {}
    }
    for (auto iterator = tail.rbegin(); iterator != tail.rend(); ++iterator)
        records->add(*iterator);
    return records;
}

std::mutex& managementAuditMutex()
{
    static std::mutex mutex;
    return mutex;
}

void appendManagementAudit(Poco::JSON::Object& record)
{
    const auto& authorization = managementAuthorization();
    if (!authorization.auditEnabled) return;
    std::ostringstream serialized;
    record.stringify(serialized);
    const std::string line = serialized.str();
    std::lock_guard<std::mutex> lock(managementAuditMutex());
    Poco::File auditFile(authorization.auditPath);
    Poco::File parent(authorization.auditPath.parent());
    if (!parent.exists()) parent.createDirectories();
    if (auditFile.exists() &&
        auditFile.getSize() + line.size() + 1 > authorization.auditMaximumBytes)
    {
        const Poco::Path archivePath(authorization.auditPath.toString() + ".1");
        if (Poco::File(archivePath).exists()) Poco::File(archivePath).remove();
        auditFile.renameTo(archivePath.toString());
    }
    Poco::FileOutputStream stream(authorization.auditPath.toString(), std::ios::app);
    stream << line << '\n';
    stream.close();
    if (!stream.good()) throw Poco::WriteFileException(authorization.auditPath.toString());
}

void recordManagementAudit(Poco::Net::HTTPServerRequest& request,
                           const std::string& principal,
                           const std::string& requestId,
                           const std::string& operation,
                           const std::string& target,
                           const std::string& action,
                           const std::string& status,
                           int httpStatus,
                           Poco::Int64 startedMicroseconds,
                           const std::string& error = {})
{
    try
    {
        const Poco::Int64 finished = Poco::Timestamp().epochMicroseconds();
        static std::atomic<std::uint64_t> sequence{0};
        Poco::JSON::Object record;
        record.set("schemaVersion", 1);
        record.set("eventId", std::to_string(finished) + "-" +
            std::to_string(sequence.fetch_add(1, std::memory_order_relaxed)));
        record.set("timestampMicroseconds", finished);
        record.set("durationMicroseconds", std::max<Poco::Int64>(0, finished - startedMicroseconds));
        record.set("principal", principal);
        record.set("requestId", requestId);
        record.set("operation", operation);
        record.set("target", target);
        record.set("action", action);
        record.set("status", status);
        record.set("httpStatus", httpStatus);
        record.set("remoteAddress", request.clientAddress().toString());
        if (!error.empty()) record.set("error", error);
        appendManagementAudit(record);
    }
    catch (...) {}
}

Poco::JSON::Array::Ptr recentManagementAudit(std::size_t limit,
                                             const std::string& operation,
                                             const std::string& status,
                                             const std::string& principal)
{
    Poco::JSON::Array::Ptr records = new Poco::JSON::Array;
    const auto& authorization = managementAuthorization();
    if (!authorization.auditEnabled || !Poco::File(authorization.auditPath).exists())
        return records;
    std::lock_guard<std::mutex> lock(managementAuditMutex());
    std::ifstream stream(authorization.auditPath.toString());
    std::deque<Poco::JSON::Object::Ptr> tail;
    std::string line;
    while (std::getline(stream, line))
    {
        try
        {
            auto item = Poco::JSON::Parser().parse(line).extract<Poco::JSON::Object::Ptr>();
            if ((!operation.empty() && item->getValue<std::string>("operation") != operation) ||
                (!status.empty() && item->getValue<std::string>("status") != status) ||
                (!principal.empty() && item->getValue<std::string>("principal") != principal))
                continue;
            tail.push_back(item);
            if (tail.size() > limit) tail.pop_front();
        }
        catch (...) {}
    }
    for (auto iterator = tail.rbegin(); iterator != tail.rend(); ++iterator)
        records->add(*iterator);
    return records;
}

void sendJsonError(Poco::Net::HTTPServerResponse& response,
                   Poco::Net::HTTPResponse::HTTPStatus status,
                   const std::string& message)
{
    Poco::JSON::Object result;
    result.set("error", message);
    response.setStatus(status);
    response.setContentType("application/json");
    result.stringify(response.send());
}

std::optional<PocoDDS::Security::AuthenticatedPrincipal> managementPrincipalForRequest(
    Poco::Net::HTTPServerRequest& request)
{
    return managementAuthorization().identityService->authenticateAuthorizationHeader(
        request.get("Authorization", ""));
}

bool managementAuthorized(Poco::Net::HTTPServerRequest& request,
                          Poco::Net::HTTPServerResponse& response,
                          const std::string& permission,
                          std::string* principalId = nullptr,
                          const std::string& operation = {})
{
    const Poco::Int64 started = Poco::Timestamp().epochMicroseconds();
    const auto& authorization = managementAuthorization();
    if (!authorization.required)
    {
        if (principalId) *principalId = "development-anonymous";
        return true;
    }
    const auto matched = managementPrincipalForRequest(request);
    if (matched)
    {
        if (matched->authorized(permission))
        {
            if (principalId) *principalId = matched->id;
            response.set("X-PDR-Management-Principal", matched->id);
            return true;
        }
        sendJsonError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                      "当前管理身份没有执行该操作的权限。");
        recordManagementAudit(request, matched->id, request.get("X-PDR-Request-Id", ""),
                              operation, "", "authorize", "denied", 403, started,
                              "permission denied: " + permission);
        return false;
    }
    response.set("WWW-Authenticate", "Bearer realm=\"pdr-management\"");
    sendJsonError(response, Poco::Net::HTTPResponse::HTTP_UNAUTHORIZED,
                  "管理操作需要有效的 Bearer 令牌。");
    recordManagementAudit(request, "", request.get("X-PDR-Request-Id", ""), operation,
                          "", "authenticate", "denied", 401, started,
                          "authentication failed");
    return false;
}

class ManagementAuditScope
{
public:
    ManagementAuditScope(Poco::Net::HTTPServerRequest& request,
                         Poco::Net::HTTPServerResponse& response,
                         std::string principal,
                         std::string operation):
        _request(request), _response(response), _principal(std::move(principal)),
        _operation(std::move(operation)),
        _started(Poco::Timestamp().epochMicroseconds())
    {
    }
    ~ManagementAuditScope()
    {
        const int code = static_cast<int>(_response.getStatus());
        const std::string status = _succeeded ? "succeeded" :
            (code >= 200 && code < 300 ? "replayed" :
             (code == 401 || code == 403 ? "denied" : "failed"));
        recordManagementAudit(_request, _principal, _requestId, _operation, _target,
                              _action, status, code, _started, _error);
    }
    void describe(std::string target, std::string action, std::string requestId)
    {
        _target = std::move(target);
        _action = std::move(action);
        _requestId = std::move(requestId);
    }
    void succeeded() { _succeeded = true; }
    void error(std::string value) { _error = std::move(value); }
private:
    Poco::Net::HTTPServerRequest& _request;
    Poco::Net::HTTPServerResponse& _response;
    std::string _principal;
    std::string _operation;
    std::string _target;
    std::string _action;
    std::string _requestId;
    std::string _error;
    Poco::Int64 _started;
    bool _succeeded{false};
};

struct ManagementTask
{
    std::string id;
    std::string operation;
    std::string target;
    std::string action;
    std::string principal;
    std::string requestId;
    std::string state{"queued"};
    std::string interruptedFromState;
    std::string recoveryPolicy{"verify-before-retry"};
    std::string error;
    Poco::Int64 submittedMicroseconds{0};
    Poco::Int64 startedMicroseconds{0};
    Poco::Int64 finishedMicroseconds{0};
    Poco::Int64 startDeadlineMicroseconds{0};
    Poco::Int64 notBeforeMicroseconds{0};
    Poco::Int64 executionDeadlineMicroseconds{0};
    int executionTimeoutMilliseconds{30000};
    bool cancellationRequested{false};
    std::string phase{"queued"};
    std::string phaseBeforeCancellation;
    std::string cancellationMode{"cooperative"};
    std::string resourceKey;
    std::string blockingTaskId;
    Poco::Int64 resourceWaitStartedMicroseconds{0};
    Poco::Int64 resourceAcquiredMicroseconds{0};
    Poco::Int64 resourceWaitMicroseconds{0};
    Poco::JSON::Object::Ptr result;
    std::shared_ptr<std::atomic<bool>> cancellationSignal{
        std::make_shared<std::atomic<bool>>(false)};
    std::function<Poco::JSON::Object::Ptr(const class ManagementTaskContext&)> execute;
};

class ManagementTaskCancelled final: public std::runtime_error
{
public:
    ManagementTaskCancelled(): std::runtime_error("management task cancellation requested") {}
};

class ManagementTaskExecutionTimedOut final: public std::runtime_error
{
public:
    ManagementTaskExecutionTimedOut(): std::runtime_error("management task execution deadline exceeded") {}
};

class ManagementTaskContext
{
public:
    ManagementTaskContext(std::shared_ptr<std::atomic<bool>> cancellationSignal,
                          Poco::Int64 executionDeadlineMicroseconds):
        _cancellationSignal(std::move(cancellationSignal)),
        _executionDeadlineMicroseconds(executionDeadlineMicroseconds)
    {
    }

    void checkpoint() const
    {
        if (_cancellationSignal->load(std::memory_order_acquire))
            throw ManagementTaskCancelled();
        if (_executionDeadlineMicroseconds > 0 &&
            Poco::Timestamp().epochMicroseconds() > _executionDeadlineMicroseconds)
            throw ManagementTaskExecutionTimedOut();
    }

private:
    std::shared_ptr<std::atomic<bool>> _cancellationSignal;
    Poco::Int64 _executionDeadlineMicroseconds;
};

Poco::JSON::Object::Ptr managementTaskJson(const ManagementTask& task)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("id", task.id);
    result->set("operation", task.operation);
    result->set("target", task.target);
    result->set("action", task.action);
    result->set("principal", task.principal);
    result->set("requestId", task.requestId);
    result->set("state", task.state);
    result->set("interruptedFromState", task.interruptedFromState);
    result->set("recoveryPolicy", task.recoveryPolicy);
    result->set("submittedMicroseconds", task.submittedMicroseconds);
    result->set("startedMicroseconds", task.startedMicroseconds);
    result->set("finishedMicroseconds", task.finishedMicroseconds);
    result->set("startDeadlineMicroseconds", task.startDeadlineMicroseconds);
    result->set("notBeforeMicroseconds", task.notBeforeMicroseconds);
    result->set("executionDeadlineMicroseconds", task.executionDeadlineMicroseconds);
    result->set("executionTimeoutMilliseconds", task.executionTimeoutMilliseconds);
    result->set("cancellationRequested", task.cancellationRequested);
    result->set("phase", task.phase);
    result->set("phaseBeforeCancellation", task.phaseBeforeCancellation);
    result->set("cancellationMode", task.cancellationMode);
    result->set("resourceKey", task.resourceKey);
    result->set("blockingTaskId", task.blockingTaskId);
    result->set("resourceWaitStartedMicroseconds", task.resourceWaitStartedMicroseconds);
    result->set("resourceAcquiredMicroseconds", task.resourceAcquiredMicroseconds);
    result->set("resourceWaitMicroseconds", task.resourceWaitMicroseconds);
    if (!task.error.empty()) result->set("error", task.error);
    if (task.result) result->set("result", task.result);
    return result;
}

struct ManagementTaskSchedulerSnapshot
{
    std::size_t workerCount{0};
    std::size_t capacity{0};
    std::size_t queued{0};
    std::size_t running{0};
    std::size_t waitingResource{0};
    std::size_t executing{0};
    std::size_t cancellationRequested{0};
    std::size_t resourceOwners{0};
    Poco::Int64 oldestQueuedWaitMicroseconds{0};
    Poco::Int64 longestResourceWaitMicroseconds{0};
    Poco::Int64 degradedWaitMicroseconds{30000000};

    bool saturated() const { return capacity > 0 && queued + running >= capacity; }
    bool excessiveWait() const
    {
        return std::max(oldestQueuedWaitMicroseconds, longestResourceWaitMicroseconds) >=
            degradedWaitMicroseconds;
    }
};

class ManagementTaskManager
{
public:
    void start(std::size_t workerCount, std::size_t capacity, std::size_t retention,
               int degradedWaitMilliseconds,
               bool persistenceEnabled, Poco::Path persistencePath)
    {
        stop();
        std::lock_guard<std::mutex> lock(_mutex);
        _capacity = capacity;
        _retention = retention;
        _degradedWaitMicroseconds = 1000LL * degradedWaitMilliseconds;
        _persistenceEnabled = persistenceEnabled;
        _persistencePath = std::move(persistencePath);
        _persistenceRecoveryRequired = false;
        _lastPersistenceError.clear();
        _previousAvailable = verifiedPreviousSnapshotAvailable(_persistencePath, "tasks");
        _resourceOwners.clear();
        _resourceWaiters.clear();
        _stopping = false;
        _started = true;
        loadLocked();
        for (std::size_t index = 0; index < workerCount; ++index)
            _workers.emplace_back([this] { run(); });
    }

    void stop()
    {
        {
            std::lock_guard<std::mutex> lock(_mutex);
            if (!_started)
            {
                _stopping = true;
                return;
            }
            _stopping = true;
            const auto now = Poco::Timestamp().epochMicroseconds();
            for (const auto& id : _queue)
            {
                auto iterator = _tasks.find(id);
                if (iterator == _tasks.end()) continue;
                iterator->second->state = "cancelled";
                iterator->second->phase = "finished";
                iterator->second->finishedMicroseconds = now;
                iterator->second->error = "Runtime is stopping";
                iterator->second->execute = {};
            }
            for (auto& item : _tasks)
            {
                if (item.second->state != "running") continue;
                item.second->cancellationRequested = true;
                item.second->cancellationSignal->store(true, std::memory_order_release);
                if (item.second->phase != "cancellation-requested")
                    item.second->phaseBeforeCancellation = item.second->phase;
                item.second->phase = "cancellation-requested";
            }
            _queue.clear();
            persistLockedNoThrow();
        }
        _condition.notify_all();
        for (auto& worker : _workers) if (worker.joinable()) worker.join();
        _workers.clear();
        std::lock_guard<std::mutex> lock(_mutex);
        _started = false;
    }

    Poco::JSON::Object::Ptr submit(std::string operation, std::string target,
                                   std::string action, std::string principal,
                                   std::string requestId, int startTimeoutMilliseconds,
                                   int notBeforeMilliseconds, int executionTimeoutMilliseconds,
                                   std::function<Poco::JSON::Object::Ptr(
                                       const ManagementTaskContext&)> execute)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (_stopping) throw Poco::IllegalStateException("management task queue is stopping");
        std::size_t active = 0;
        for (const auto& item : _tasks)
            if (item.second->state == "queued" || item.second->state == "running") ++active;
        if (active >= _capacity)
            throw Poco::IllegalStateException("management task queue capacity reached");
        static std::atomic<std::uint64_t> sequence{0};
        auto task = std::make_shared<ManagementTask>();
        task->submittedMicroseconds = Poco::Timestamp().epochMicroseconds();
        task->id = "management-task-" + std::to_string(task->submittedMicroseconds) + "-" +
            std::to_string(sequence.fetch_add(1, std::memory_order_relaxed));
        task->operation = std::move(operation);
        task->target = std::move(target);
        task->action = std::move(action);
        task->principal = std::move(principal);
        task->requestId = std::move(requestId);
        task->resourceKey = task->operation + ":" + task->target;
        task->startDeadlineMicroseconds = task->submittedMicroseconds +
            1000LL * startTimeoutMilliseconds;
        task->notBeforeMicroseconds = task->submittedMicroseconds +
            1000LL * notBeforeMilliseconds;
        task->executionDeadlineMicroseconds = 0;
        task->executionTimeoutMilliseconds = executionTimeoutMilliseconds;
        task->execute = std::move(execute);
        _tasks[task->id] = task;
        _order.push_back(task->id);
        _queue.push_back(task->id);
        pruneLocked();
        try { persistLocked(); }
        catch (...)
        {
            _queue.pop_back();
            _order.pop_back();
            _tasks.erase(task->id);
            throw;
        }
        _condition.notify_one();
        return managementTaskJson(*task);
    }

    Poco::JSON::Object::Ptr get(const std::string& id)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        const auto iterator = _tasks.find(id);
        return iterator == _tasks.end() ? nullptr : managementTaskJson(*iterator->second);
    }

    Poco::JSON::Array::Ptr list(std::size_t limit, const std::string& state,
                                const std::string& operation)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        Poco::JSON::Array::Ptr result = new Poco::JSON::Array;
        for (auto iterator = _order.rbegin(); iterator != _order.rend() && result->size() < limit;
             ++iterator)
        {
            const auto found = _tasks.find(*iterator);
            if (found == _tasks.end()) continue;
            const auto& task = *found->second;
            if ((!state.empty() && task.state != state) ||
                (!operation.empty() && task.operation != operation)) continue;
            result->add(managementTaskJson(task));
        }
        return result;
    }

    Poco::JSON::Object::Ptr persistenceStatus()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        Poco::JSON::Object::Ptr status = new Poco::JSON::Object;
        status->set("enabled", _persistenceEnabled);
        status->set("healthy", !_persistenceEnabled || _lastPersistenceError.empty());
        status->set("error", _lastPersistenceError);
        status->set("recoveryRequired", _persistenceRecoveryRequired);
        status->set("schemaVersion", 2);
        status->set("integrityAlgorithm", "SHA-256");
        status->set("previousAvailable", _previousAvailable);
        return status;
    }

    ManagementTaskSchedulerSnapshot schedulerSnapshot()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        ManagementTaskSchedulerSnapshot result;
        result.workerCount = _workers.size();
        result.capacity = _capacity;
        result.resourceOwners = _resourceOwners.size();
        result.degradedWaitMicroseconds = _degradedWaitMicroseconds;
        const auto now = Poco::Timestamp().epochMicroseconds();
        for (const auto& item : _tasks)
        {
            const auto& task = *item.second;
            if (task.state == "queued")
            {
                ++result.queued;
                const auto eligibleSince = std::max(task.submittedMicroseconds,
                                                    task.notBeforeMicroseconds);
                if (now > eligibleSince)
                    result.oldestQueuedWaitMicroseconds = std::max(
                        result.oldestQueuedWaitMicroseconds, now - eligibleSince);
            }
            else if (task.state == "running")
            {
                ++result.running;
                if (task.phase == "waiting-resource")
                {
                    ++result.waitingResource;
                    result.longestResourceWaitMicroseconds = std::max(
                        result.longestResourceWaitMicroseconds,
                        now - task.resourceWaitStartedMicroseconds);
                }
                else if (task.phase == "executing") ++result.executing;
                if (task.cancellationRequested) ++result.cancellationRequested;
            }
        }
        auto& metrics = PocoDDS::Observability::Metrics::global();
        metrics.recordHistogram("pdr.management.tasks.queue.depth",
            static_cast<double>(result.queued), {}, "Queued management tasks", "{task}");
        metrics.recordHistogram("pdr.management.tasks.workers.active",
            static_cast<double>(result.running), {}, "Active management task workers", "{worker}");
        metrics.recordHistogram("pdr.management.tasks.resource.waiting",
            static_cast<double>(result.waitingResource), {},
            "Management tasks waiting for a resource", "{task}");
        metrics.recordHistogram("pdr.management.tasks.queue.utilization",
            result.capacity == 0 ? 0.0 :
                100.0 * static_cast<double>(result.queued + result.running) /
                    static_cast<double>(result.capacity), {},
            "Management task capacity utilization", "%");
        metrics.recordHistogram("pdr.management.tasks.wait.max",
            static_cast<double>(std::max(result.oldestQueuedWaitMicroseconds,
                                         result.longestResourceWaitMicroseconds)) / 1000.0,
            {}, "Longest management task wait", "ms");
        return result;
    }

    Poco::JSON::Object::Ptr schedulerStatus()
    {
        const auto snapshot = schedulerSnapshot();
        Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
        result->set("workerCount", snapshot.workerCount);
        result->set("capacity", snapshot.capacity);
        result->set("queued", snapshot.queued);
        result->set("running", snapshot.running);
        result->set("waitingResource", snapshot.waitingResource);
        result->set("executing", snapshot.executing);
        result->set("cancellationRequested", snapshot.cancellationRequested);
        result->set("resourceOwners", snapshot.resourceOwners);
        result->set("oldestQueuedWaitMicroseconds", snapshot.oldestQueuedWaitMicroseconds);
        result->set("longestResourceWaitMicroseconds", snapshot.longestResourceWaitMicroseconds);
        result->set("degradedWaitMicroseconds", snapshot.degradedWaitMicroseconds);
        result->set("saturated", snapshot.saturated());
        result->set("degraded", snapshot.saturated() || snapshot.excessiveWait());
        return result;
    }

    Poco::JSON::Object::Ptr cancel(const std::string& id)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        const auto iterator = _tasks.find(id);
        if (iterator == _tasks.end()) return nullptr;
        auto& task = *iterator->second;
        if (task.state == "queued")
        {
            task.cancellationRequested = true;
            task.cancellationSignal->store(true, std::memory_order_release);
            task.state = "cancelled";
            task.phase = "finished";
            task.finishedMicroseconds = Poco::Timestamp().epochMicroseconds();
            task.execute = {};
            _queue.erase(std::remove(_queue.begin(), _queue.end(), id), _queue.end());
        }
        else if (task.state == "running")
        {
            task.cancellationRequested = true;
            task.cancellationSignal->store(true, std::memory_order_release);
            if (task.phase != "cancellation-requested")
                task.phaseBeforeCancellation = task.phase;
            task.phase = "cancellation-requested";
        }
        persistLockedNoThrow();
        _condition.notify_all();
        return managementTaskJson(task);
    }

private:
    void run()
    {
        while (true)
        {
            std::shared_ptr<ManagementTask> task;
            {
                std::unique_lock<std::mutex> lock(_mutex);
                while (!task)
                {
                    if (_queue.empty())
                        _condition.wait(lock, [this] { return _stopping || !_queue.empty(); });
                    if (_stopping && _queue.empty()) return;
                    const auto now = Poco::Timestamp().epochMicroseconds();
                    Poco::Int64 nextWakeMicroseconds = 0;
                    for (auto queued = _queue.begin(); queued != _queue.end();)
                    {
                        const auto iterator = _tasks.find(*queued);
                        if (iterator == _tasks.end() || iterator->second->state != "queued")
                        {
                            queued = _queue.erase(queued);
                            continue;
                        }
                        auto candidate = iterator->second;
                        if (now > candidate->startDeadlineMicroseconds)
                        {
                            candidate->state = "timed-out";
                            candidate->phase = "finished";
                            candidate->finishedMicroseconds = now;
                            candidate->error = "task did not start before its deadline";
                            candidate->execute = {};
                            queued = _queue.erase(queued);
                            persistLockedNoThrow();
                            continue;
                        }
                        if (now >= candidate->notBeforeMicroseconds)
                        {
                            task = candidate;
                            _queue.erase(queued);
                            break;
                        }
                        if (nextWakeMicroseconds == 0 ||
                            candidate->notBeforeMicroseconds < nextWakeMicroseconds)
                            nextWakeMicroseconds = candidate->notBeforeMicroseconds;
                        ++queued;
                    }
                    if (task) break;
                    if (_stopping && _queue.empty()) return;
                    if (nextWakeMicroseconds > now)
                        _condition.wait_for(lock, std::chrono::microseconds(
                            nextWakeMicroseconds - now));
                }
                const auto now = Poco::Timestamp().epochMicroseconds();
                task->state = "running";
                task->phase = "executing";
                task->startedMicroseconds = now;
                task->executionDeadlineMicroseconds = now +
                    1000LL * task->executionTimeoutMilliseconds;
                persistLockedNoThrow();
            }
            try
            {
                ManagementTaskContext context(task->cancellationSignal,
                                              task->executionDeadlineMicroseconds);
                context.checkpoint();
                acquireResource(task, context);
                auto result = task->execute(context);
                context.checkpoint();
                std::lock_guard<std::mutex> lock(_mutex);
                task->result = result;
                task->state = "succeeded";
                task->phase = "finished";
            }
            catch (const ManagementTaskCancelled& exception)
            {
                std::lock_guard<std::mutex> lock(_mutex);
                task->state = "cancelled";
                task->phase = "finished";
                task->error = exception.what();
            }
            catch (const ManagementTaskExecutionTimedOut& exception)
            {
                std::lock_guard<std::mutex> lock(_mutex);
                task->state = "timed-out";
                task->phase = "finished";
                task->error = exception.what();
            }
            catch (const std::exception& exception)
            {
                std::lock_guard<std::mutex> lock(_mutex);
                task->state = "failed";
                task->phase = "finished";
                task->error = exception.what();
            }
            releaseResource(task);
            {
                std::lock_guard<std::mutex> lock(_mutex);
                task->finishedMicroseconds = Poco::Timestamp().epochMicroseconds();
                task->execute = {};
                pruneLocked();
                persistLockedNoThrow();
            }
        }
    }

    void acquireResource(const std::shared_ptr<ManagementTask>& task,
                         const ManagementTaskContext& context)
    {
        std::unique_lock<std::mutex> lock(_mutex);
        _resourceWaiters[task->resourceKey].push_back(task->id);
        task->resourceWaitStartedMicroseconds = Poco::Timestamp().epochMicroseconds();
        task->phase = "waiting-resource";
        persistLockedNoThrow();
        try
        {
            while (true)
            {
                context.checkpoint();
                const auto owner = _resourceOwners.find(task->resourceKey);
                auto waiter = _resourceWaiters.find(task->resourceKey);
                if (owner == _resourceOwners.end() && waiter != _resourceWaiters.end() &&
                    !waiter->second.empty() && waiter->second.front() == task->id)
                {
                    waiter->second.pop_front();
                    if (waiter->second.empty()) _resourceWaiters.erase(waiter);
                    _resourceOwners[task->resourceKey] = task->id;
                    task->resourceAcquiredMicroseconds =
                        Poco::Timestamp().epochMicroseconds();
                    task->resourceWaitMicroseconds =
                        task->resourceAcquiredMicroseconds -
                        task->resourceWaitStartedMicroseconds;
                    task->phase = "executing";
                    persistLockedNoThrow();
                    return;
                }
                task->blockingTaskId = owner == _resourceOwners.end() ? "" : owner->second;
                _condition.wait_for(lock, std::chrono::milliseconds(25));
            }
        }
        catch (...)
        {
            auto found = _resourceWaiters.find(task->resourceKey);
            if (found != _resourceWaiters.end())
            {
                found->second.erase(std::remove(found->second.begin(), found->second.end(),
                                                task->id), found->second.end());
                if (found->second.empty()) _resourceWaiters.erase(found);
            }
            task->resourceWaitMicroseconds = Poco::Timestamp().epochMicroseconds() -
                task->resourceWaitStartedMicroseconds;
            throw;
        }
    }

    void releaseResource(const std::shared_ptr<ManagementTask>& task)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        const auto owner = _resourceOwners.find(task->resourceKey);
        if (owner != _resourceOwners.end() && owner->second == task->id)
            _resourceOwners.erase(owner);
        _condition.notify_all();
    }

    void pruneLocked()
    {
        while (_order.size() > _retention)
        {
            const auto removable = std::find_if(_order.begin(), _order.end(), [this](const auto& id) {
                const auto iterator = _tasks.find(id);
                return iterator == _tasks.end() ||
                    (iterator->second->state != "queued" && iterator->second->state != "running");
            });
            if (removable == _order.end()) break;
            _tasks.erase(*removable);
            _order.erase(removable);
        }
    }

    void loadLocked()
    {
        _tasks.clear();
        _queue.clear();
        _order.clear();
        if (!_persistenceEnabled || !Poco::File(_persistencePath).exists())
        {
            _lastPersistenceError.clear();
            _persistenceRecoveryRequired = false;
            return;
        }
        try
        {
            Poco::FileInputStream stream(_persistencePath.toString());
            auto root = Poco::JSON::Parser().parse(stream).extract<Poco::JSON::Object::Ptr>();
            stream.close();
            const int schemaVersion = root->optValue<int>("schemaVersion", 0);
            if (schemaVersion != 1 && schemaVersion != 2)
                throw Poco::DataFormatException(
                    "unsupported management task snapshot schema");
            auto tasks = root->getArray("tasks");
            if (!tasks)
                throw Poco::DataFormatException(
                    "management task snapshot is missing tasks array");
            if (schemaVersion == 2)
            {
                std::ostringstream serializedTasks;
                tasks->stringify(serializedTasks);
                if (root->optValue<std::string>("contentSha256", "") !=
                    sha256Digest(serializedTasks.str()))
                    throw Poco::DataFormatException(
                        "management task snapshot integrity check failed");
            }
            const auto now = Poco::Timestamp().epochMicroseconds();
            const std::size_t first = tasks->size() > _retention ?
                tasks->size() - _retention : 0;
            for (std::size_t index = first; index < tasks->size(); ++index)
            {
                auto source = tasks->getObject(static_cast<unsigned>(index));
                if (!source) continue;
                auto task = std::make_shared<ManagementTask>();
                task->id = source->optValue<std::string>("id", "");
                if (task->id.empty()) continue;
                task->operation = source->optValue<std::string>("operation", "");
                task->target = source->optValue<std::string>("target", "");
                task->action = source->optValue<std::string>("action", "");
                task->principal = source->optValue<std::string>("principal", "");
                task->requestId = source->optValue<std::string>("requestId", "");
                task->state = source->optValue<std::string>("state", "failed");
                task->error = source->optValue<std::string>("error", "");
                task->submittedMicroseconds = source->optValue<Poco::Int64>(
                    "submittedMicroseconds", 0);
                task->startedMicroseconds = source->optValue<Poco::Int64>(
                    "startedMicroseconds", 0);
                task->finishedMicroseconds = source->optValue<Poco::Int64>(
                    "finishedMicroseconds", 0);
                task->startDeadlineMicroseconds = source->optValue<Poco::Int64>(
                    "startDeadlineMicroseconds", 0);
                task->notBeforeMicroseconds = source->optValue<Poco::Int64>(
                    "notBeforeMicroseconds", task->submittedMicroseconds);
                task->executionDeadlineMicroseconds = source->optValue<Poco::Int64>(
                    "executionDeadlineMicroseconds", 0);
                task->executionTimeoutMilliseconds = source->optValue<int>(
                    "executionTimeoutMilliseconds", 30000);
                task->cancellationRequested = source->optValue<bool>(
                    "cancellationRequested", false);
                task->cancellationSignal->store(task->cancellationRequested,
                                                std::memory_order_release);
                task->phase = source->optValue<std::string>("phase", "finished");
                task->phaseBeforeCancellation = source->optValue<std::string>(
                    "phaseBeforeCancellation", "");
                task->cancellationMode = source->optValue<std::string>(
                    "cancellationMode", "cooperative");
                task->resourceKey = source->optValue<std::string>(
                    "resourceKey", task->operation + ":" + task->target);
                task->blockingTaskId = source->optValue<std::string>("blockingTaskId", "");
                task->resourceWaitStartedMicroseconds = source->optValue<Poco::Int64>(
                    "resourceWaitStartedMicroseconds", 0);
                task->resourceAcquiredMicroseconds = source->optValue<Poco::Int64>(
                    "resourceAcquiredMicroseconds", 0);
                task->resourceWaitMicroseconds = source->optValue<Poco::Int64>(
                    "resourceWaitMicroseconds", 0);
                task->recoveryPolicy = source->optValue<std::string>(
                    "recoveryPolicy", "verify-before-retry");
                task->interruptedFromState = source->optValue<std::string>(
                    "interruptedFromState", "");
                if (source->has("result")) task->result = source->getObject("result");
                if (task->state == "queued" || task->state == "running")
                {
                    task->interruptedFromState = task->state;
                    task->state = "interrupted";
                    task->phase = "finished";
                    task->finishedMicroseconds = now;
                    task->error = "Runtime stopped before the task reached a terminal state; "
                                  "verify the target before retrying";
                    task->execute = {};
                }
                _tasks[task->id] = task;
                _order.push_back(task->id);
            }
            pruneLocked();
            persistLockedNoThrow();
            _persistenceRecoveryRequired = false;
        }
        catch (const std::exception& exception)
        {
            _lastPersistenceError = exception.what();
            _persistenceRecoveryRequired = true;
            _tasks.clear();
            _queue.clear();
            _order.clear();
        }
    }

    void persistLocked()
    {
        if (!_persistenceEnabled) return;
        if (_persistenceRecoveryRequired)
            throw Poco::IllegalStateException(
                "management task persistence requires operator recovery");
        Poco::JSON::Array::Ptr tasks = new Poco::JSON::Array;
        for (const auto& id : _order)
        {
            const auto iterator = _tasks.find(id);
            if (iterator != _tasks.end()) tasks->add(managementTaskJson(*iterator->second));
        }
        Poco::JSON::Object root;
        std::ostringstream serializedTasks;
        tasks->stringify(serializedTasks);
        root.set("schemaVersion", 2);
        root.set("savedAtMicroseconds", Poco::Timestamp().epochMicroseconds());
        root.set("contentSha256", sha256Digest(serializedTasks.str()));
        root.set("tasks", tasks);
        Poco::File parent(_persistencePath.parent());
        if (!parent.exists()) parent.createDirectories();
        Poco::Path staged(_persistencePath.toString() + ".new");
        if (Poco::File(staged).exists()) Poco::File(staged).remove();
        Poco::FileOutputStream stream(staged.toString());
        root.stringify(stream);
        stream.close();
        if (!stream.good()) throw Poco::WriteFileException(staged.toString());
        (void) readJsonObject(staged);
        preservePreviousSnapshot(_persistencePath, "tasks");
        replaceConfigurationFile(staged, _persistencePath);
        _previousAvailable = verifiedPreviousSnapshotAvailable(_persistencePath, "tasks");
        _lastPersistenceError.clear();
    }

    void persistLockedNoThrow()
    {
        try { persistLocked(); }
        catch (const std::exception& exception) { _lastPersistenceError = exception.what(); }
    }

    std::mutex _mutex;
    std::condition_variable _condition;
    std::unordered_map<std::string, std::shared_ptr<ManagementTask>> _tasks;
    std::deque<std::string> _queue;
    std::deque<std::string> _order;
    std::vector<std::thread> _workers;
    std::unordered_map<std::string, std::string> _resourceOwners;
    std::unordered_map<std::string, std::deque<std::string>> _resourceWaiters;
    std::size_t _capacity{100};
    std::size_t _retention{1000};
    Poco::Int64 _degradedWaitMicroseconds{30000000};
    bool _stopping{true};
    bool _started{false};
    bool _persistenceEnabled{true};
    Poco::Path _persistencePath{"management-tasks.json"};
    std::string _lastPersistenceError;
    bool _persistenceRecoveryRequired{false};
    bool _previousAvailable{false};
};

ManagementTaskManager& managementTaskManager()
{
    static ManagementTaskManager manager;
    return manager;
}

bool managementTaskSubmissionAvailable(Poco::Net::HTTPServerResponse& response)
{
    const auto persistence = managementTaskManager().persistenceStatus();
    if (persistence->optValue<bool>("healthy", false)) return true;
    sendJsonError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                  "管理任务快照需要运维恢复，当前拒绝提交新的异步任务。");
    return false;
}

Poco::JSON::Object::Ptr managementRequestLedgerStatus();

PocoDDS::Health::Report managementTaskHealthReport()
{
    const auto scheduler = managementTaskManager().schedulerSnapshot();
    const auto persistence = managementTaskManager().persistenceStatus();
    const auto idempotency = managementRequestLedgerStatus();
    const bool persistenceHealthy = persistence->optValue<bool>("healthy", false);
    const bool idempotencyHealthy = idempotency->optValue<bool>("healthy", false);
    const bool healthy = !scheduler.saturated() && !scheduler.excessiveWait() &&
        persistenceHealthy && idempotencyHealthy;
    std::string code;
    std::string remediation;
    if (!persistenceHealthy)
    {
        code = "PDR-HEALTH-MANAGEMENT-TASK-PERSISTENCE_FAILED";
        remediation = "Inspect the task snapshot path, free space and file permissions before submitting more management operations.";
    }
    else if (!idempotencyHealthy)
    {
        code = "PDR-HEALTH-MANAGEMENT-IDEMPOTENCY-PERSISTENCE_FAILED";
        remediation = "Inspect the idempotency ledger path, free space and file permissions before retrying management operations.";
    }
    else if (scheduler.saturated())
    {
        code = "PDR-HEALTH-MANAGEMENT-TASK-QUEUE_SATURATED";
        remediation = "Inspect queued tasks and blocking resource owners; cancel obsolete work or increase capacity only after root-cause review.";
    }
    else if (scheduler.excessiveWait())
    {
        code = "PDR-HEALTH-MANAGEMENT-TASK-WAIT_EXCESSIVE";
        remediation = "Inspect blockingTaskId and the target operation, then cancel or repair the blocking operation.";
    }
    return PocoDDS::Health::Report{
        "management-tasks",
        healthy ? PocoDDS::Health::Status::up : PocoDDS::Health::Status::degraded,
        std::to_string(scheduler.queued) + " queued, " +
            std::to_string(scheduler.running) + "/" +
            std::to_string(scheduler.workerCount) + " workers active, " +
            std::to_string(scheduler.waitingResource) + " waiting for resource",
        code, remediation};
}

class ManagementTaskHealthService final : public Poco::OSP::Service,
                                          public PocoDDS::Health::IHealthContributor
{
public:
    const std::type_info& type() const override { return typeid(ManagementTaskHealthService); }
    bool isA(const std::type_info& otherType) const override
    {
        return std::string(typeid(ManagementTaskHealthService).name()) == otherType.name() ||
            Poco::OSP::Service::isA(otherType);
    }
    PocoDDS::Health::Report health() const override { return managementTaskHealthReport(); }
};

struct ManagementRequestEntry
{
    std::string fingerprintDigest;
    std::string operation;
    std::string target;
    std::string action;
    Poco::Int64 updatedMicroseconds{0};
    bool completed{false};
    bool interrupted{false};
};

struct ManagementRequestLedgerConfiguration
{
    bool persistenceEnabled{true};
    Poco::Path persistencePath{"management-idempotency.json"};
    std::size_t retention{1000};
    Poco::Int64 ttlMicroseconds{86400000000LL};
    std::string lastPersistenceError;
    bool recoveryRequired{false};
    bool previousAvailable{false};
};

std::mutex& managementRequestMutex()
{
    static std::mutex mutex;
    return mutex;
}

std::unordered_map<std::string, ManagementRequestEntry>& managementRequests()
{
    static std::unordered_map<std::string, ManagementRequestEntry> entries;
    return entries;
}

ManagementRequestLedgerConfiguration& managementRequestLedgerConfiguration()
{
    static ManagementRequestLedgerConfiguration configuration;
    return configuration;
}

std::string managementRequestFingerprintDigest(const std::string& fingerprint)
{
    return sha256Digest(fingerprint);
}

void pruneManagementRequestsLocked(Poco::Int64 now)
{
    auto& entries = managementRequests();
    const auto ttl = managementRequestLedgerConfiguration().ttlMicroseconds;
    for (auto iterator = entries.begin(); iterator != entries.end();)
    {
        if (now - iterator->second.updatedMicroseconds > ttl)
            iterator = entries.erase(iterator);
        else ++iterator;
    }
    const auto retention = managementRequestLedgerConfiguration().retention;
    while (entries.size() > retention)
    {
        const auto oldest = std::min_element(entries.begin(), entries.end(),
            [](const auto& left, const auto& right) {
                return left.second.updatedMicroseconds < right.second.updatedMicroseconds;
            });
        if (oldest == entries.end()) break;
        entries.erase(oldest);
    }
}

void persistManagementRequestsLocked()
{
    auto& configuration = managementRequestLedgerConfiguration();
    if (!configuration.persistenceEnabled) return;
    if (configuration.recoveryRequired)
        throw Poco::IllegalStateException(
            "management idempotency persistence requires operator recovery");
    Poco::JSON::Array::Ptr requests = new Poco::JSON::Array;
    std::vector<std::pair<std::string, ManagementRequestEntry>> ordered(
        managementRequests().begin(), managementRequests().end());
    std::sort(ordered.begin(), ordered.end(), [](const auto& left, const auto& right) {
        return left.second.updatedMicroseconds < right.second.updatedMicroseconds;
    });
    for (const auto& item : ordered)
    {
        Poco::JSON::Object::Ptr request = new Poco::JSON::Object;
        request->set("requestId", item.first);
        request->set("fingerprintSha256", item.second.fingerprintDigest);
        request->set("operation", item.second.operation);
        request->set("target", item.second.target);
        request->set("action", item.second.action);
        request->set("updatedMicroseconds", item.second.updatedMicroseconds);
        request->set("state", item.second.completed ? "completed" :
                     item.second.interrupted ? "interrupted" : "in-progress");
        requests->add(request);
    }
    Poco::JSON::Object root;
    std::ostringstream serializedRequests;
    requests->stringify(serializedRequests);
    root.set("schemaVersion", 2);
    root.set("savedAtMicroseconds", Poco::Timestamp().epochMicroseconds());
    root.set("contentSha256", sha256Digest(serializedRequests.str()));
    root.set("requests", requests);
    Poco::File parent(configuration.persistencePath.parent());
    if (!parent.exists()) parent.createDirectories();
    Poco::Path staged(configuration.persistencePath.toString() + ".new");
    if (Poco::File(staged).exists()) Poco::File(staged).remove();
    Poco::FileOutputStream stream(staged.toString());
    root.stringify(stream);
    stream.close();
    if (!stream.good()) throw Poco::WriteFileException(staged.toString());
    (void) readJsonObject(staged);
    preservePreviousSnapshot(configuration.persistencePath, "requests");
    replaceConfigurationFile(staged, configuration.persistencePath);
    configuration.previousAvailable = verifiedPreviousSnapshotAvailable(
        configuration.persistencePath, "requests");
    configuration.lastPersistenceError.clear();
}

void persistManagementRequestsNoThrowLocked()
{
    try { persistManagementRequestsLocked(); }
    catch (const std::exception& exception)
    {
        managementRequestLedgerConfiguration().lastPersistenceError = exception.what();
        managementRequestLedgerConfiguration().recoveryRequired = true;
    }
}

void configureManagementRequestLedger(const Poco::Util::AbstractConfiguration& config)
{
    std::lock_guard<std::mutex> lock(managementRequestMutex());
    auto& configuration = managementRequestLedgerConfiguration();
    configuration.persistenceEnabled = config.getBool(
        "pdr.management.idempotency.persistence.enabled", true);
    configuration.persistencePath = Poco::Path(config.expand(config.getString(
        "pdr.management.idempotency.persistence.path",
        "${application.dir}management-idempotency.json"))).makeAbsolute();
    configuration.retention = static_cast<std::size_t>(std::max(1,
        config.getInt("pdr.management.idempotency.retention", 1000)));
    configuration.ttlMicroseconds = 1000LL * std::max<Poco::Int64>(1,
        config.getInt64("pdr.management.idempotency.ttlMilliseconds", 86400000));
    configuration.lastPersistenceError.clear();
    configuration.recoveryRequired = false;
    configuration.previousAvailable = verifiedPreviousSnapshotAvailable(
        configuration.persistencePath, "requests");
    managementRequests().clear();
    if (!configuration.persistenceEnabled || !Poco::File(configuration.persistencePath).exists())
        return;
    try
    {
        Poco::FileInputStream stream(configuration.persistencePath.toString());
        auto root = Poco::JSON::Parser().parse(stream).extract<Poco::JSON::Object::Ptr>();
        stream.close();
        const int schemaVersion = root->optValue<int>("schemaVersion", 0);
        if (schemaVersion != 1 && schemaVersion != 2)
            throw Poco::DataFormatException(
                "unsupported management idempotency ledger schema");
        auto requests = root->getArray("requests");
        if (!requests)
            throw Poco::DataFormatException(
                "management idempotency ledger is missing requests array");
        if (schemaVersion == 2)
        {
            std::ostringstream serializedRequests;
            requests->stringify(serializedRequests);
            if (root->optValue<std::string>("contentSha256", "") !=
                sha256Digest(serializedRequests.str()))
                throw Poco::DataFormatException(
                    "management idempotency ledger integrity check failed");
        }
        const auto now = Poco::Timestamp().epochMicroseconds();
        if (requests)
        {
            for (std::size_t index = 0; index < requests->size(); ++index)
            {
                auto source = requests->getObject(static_cast<unsigned>(index));
                if (!source) continue;
                const auto requestId = source->optValue<std::string>("requestId", "");
                ManagementRequestEntry entry;
                entry.fingerprintDigest = source->optValue<std::string>("fingerprintSha256", "");
                entry.operation = source->optValue<std::string>("operation", "");
                entry.target = source->optValue<std::string>("target", "");
                entry.action = source->optValue<std::string>("action", "");
                entry.updatedMicroseconds = source->optValue<Poco::Int64>(
                    "updatedMicroseconds", 0);
                const auto state = source->optValue<std::string>("state", "interrupted");
                entry.completed = state == "completed";
                entry.interrupted = !entry.completed;
                if (!requestId.empty() && entry.fingerprintDigest.size() == 64)
                    managementRequests()[requestId] = std::move(entry);
            }
        }
        pruneManagementRequestsLocked(now);
        persistManagementRequestsLocked();
    }
    catch (const std::exception& exception)
    {
        configuration.lastPersistenceError = exception.what();
        configuration.recoveryRequired = true;
        managementRequests().clear();
    }
}

Poco::JSON::Object::Ptr managementRequestLedgerStatus()
{
    std::lock_guard<std::mutex> lock(managementRequestMutex());
    const auto& configuration = managementRequestLedgerConfiguration();
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    std::size_t completed = 0;
    std::size_t interrupted = 0;
    for (const auto& item : managementRequests())
    {
        if (item.second.completed) ++completed;
        else if (item.second.interrupted) ++interrupted;
    }
    result->set("enabled", configuration.persistenceEnabled);
    result->set("healthy", !configuration.persistenceEnabled ||
                configuration.lastPersistenceError.empty());
    result->set("error", configuration.lastPersistenceError);
    result->set("recoveryRequired", configuration.recoveryRequired);
    result->set("schemaVersion", 2);
    result->set("integrityAlgorithm", "SHA-256");
    result->set("previousAvailable", configuration.previousAvailable);
    result->set("count", managementRequests().size());
    result->set("completed", completed);
    result->set("interrupted", interrupted);
    result->set("retention", configuration.retention);
    result->set("ttlMilliseconds", configuration.ttlMicroseconds / 1000);
    return result;
}

class ManagementRequestGuard
{
public:
    ManagementRequestGuard() = default;
    ManagementRequestGuard(std::string requestId, bool proceed, bool tracked):
        _requestId(std::move(requestId)), _proceed(proceed), _tracked(tracked)
    {
    }
    ManagementRequestGuard(const ManagementRequestGuard&) = delete;
    ManagementRequestGuard& operator=(const ManagementRequestGuard&) = delete;
    ManagementRequestGuard(ManagementRequestGuard&& other) noexcept:
        _requestId(std::move(other._requestId)), _proceed(other._proceed),
        _tracked(other._tracked)
    {
        other._tracked = false;
    }
    ManagementRequestGuard& operator=(ManagementRequestGuard&& other) noexcept
    {
        if (this == &other) return *this;
        if (_tracked)
        {
            std::lock_guard<std::mutex> lock(managementRequestMutex());
            const auto iterator = managementRequests().find(_requestId);
            if (iterator != managementRequests().end() && !iterator->second.completed)
            {
                managementRequests().erase(iterator);
                persistManagementRequestsNoThrowLocked();
            }
        }
        _requestId = std::move(other._requestId);
        _proceed = other._proceed;
        _tracked = other._tracked;
        other._tracked = false;
        return *this;
    }
    ~ManagementRequestGuard()
    {
        if (!_tracked) return;
        std::lock_guard<std::mutex> lock(managementRequestMutex());
        const auto iterator = managementRequests().find(_requestId);
        if (iterator != managementRequests().end() && !iterator->second.completed)
        {
            managementRequests().erase(iterator);
            persistManagementRequestsNoThrowLocked();
        }
    }
    [[nodiscard]] bool proceed() const { return _proceed; }
    [[nodiscard]] const std::string& requestId() const { return _requestId; }
    void complete(const std::string& operation, const std::string& target,
                  const std::string& action)
    {
        if (!_tracked) return;
        std::lock_guard<std::mutex> lock(managementRequestMutex());
        auto iterator = managementRequests().find(_requestId);
        if (iterator == managementRequests().end()) return;
        iterator->second.operation = operation;
        iterator->second.target = target;
        iterator->second.action = action;
        iterator->second.completed = true;
        iterator->second.interrupted = false;
        iterator->second.updatedMicroseconds = Poco::Timestamp().epochMicroseconds();
        persistManagementRequestsNoThrowLocked();
        _tracked = false;
    }
private:
    std::string _requestId;
    bool _proceed{true};
    bool _tracked{false};
};

ManagementRequestGuard beginManagementRequest(
    Poco::Net::HTTPServerRequest& request,
    Poco::Net::HTTPServerResponse& response,
    const std::string& fingerprint)
{
    const std::string requestId = request.get("X-PDR-Request-Id", "");
    if (requestId.empty())
    {
        if (!managementAuthorization().requireRequestId)
            return ManagementRequestGuard({}, true, false);
        return sendJsonError(response, static_cast<Poco::Net::HTTPResponse::HTTPStatus>(428),
                             "管理写操作需要 X-PDR-Request-Id。"),
               ManagementRequestGuard({}, false, false);
    }
    if (requestId.size() > 128 ||
        !std::regex_match(requestId, std::regex("[A-Za-z0-9][A-Za-z0-9_.:-]*")))
        return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                             "X-PDR-Request-Id 格式无效。"),
               ManagementRequestGuard({}, false, false);

    const auto now = Poco::Timestamp().epochMicroseconds();
    const auto fingerprintDigest = managementRequestFingerprintDigest(fingerprint);
    std::lock_guard<std::mutex> lock(managementRequestMutex());
    auto& ledgerConfiguration = managementRequestLedgerConfiguration();
    if (ledgerConfiguration.persistenceEnabled && ledgerConfiguration.recoveryRequired)
        return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                             "管理幂等账本需要运维恢复，当前拒绝执行新的管理写操作。"),
               ManagementRequestGuard({}, false, false);
    auto& entries = managementRequests();
    pruneManagementRequestsLocked(now);
    const auto existing = entries.find(requestId);
    if (existing != entries.end())
    {
        if (existing->second.fingerprintDigest != fingerprintDigest)
            return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_CONFLICT,
                                 "X-PDR-Request-Id 已用于不同的管理操作。"),
                   ManagementRequestGuard({}, false, false);
        if (existing->second.interrupted)
            return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_CONFLICT,
                                 "该管理请求在 Runtime 重启前未确认完成；请先核对目标状态，再使用新的请求 ID。"),
                   ManagementRequestGuard({}, false, false);
        if (!existing->second.completed)
            return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_CONFLICT,
                                 "相同管理请求仍在执行。"),
                   ManagementRequestGuard({}, false, false);
        Poco::JSON::Object replay;
        replay.set("message", "重复管理请求未再次执行");
        replay.set("requestId", requestId);
        replay.set("idempotentReplay", true);
        replay.set("operation", existing->second.operation);
        replay.set("target", existing->second.target);
        replay.set("action", existing->second.action);
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json");
        replay.stringify(response.send());
        return ManagementRequestGuard({}, false, false);
    }
    if (entries.size() >= managementRequestLedgerConfiguration().retention)
    {
        const auto oldest = std::min_element(entries.begin(), entries.end(),
            [](const auto& left, const auto& right) {
                return left.second.updatedMicroseconds < right.second.updatedMicroseconds;
            });
        if (oldest != entries.end()) entries.erase(oldest);
    }
    entries.emplace(requestId, ManagementRequestEntry{
        fingerprintDigest, {}, {}, {}, now, false, false});
    try { persistManagementRequestsLocked(); }
    catch (...)
    {
        entries.erase(requestId);
        try { throw; }
        catch (const std::exception& exception)
        {
            ledgerConfiguration.lastPersistenceError = exception.what();
            ledgerConfiguration.recoveryRequired = true;
        }
        return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                             "管理幂等账本无法持久化，当前拒绝执行管理写操作。"),
               ManagementRequestGuard({}, false, false);
    }
    return ManagementRequestGuard(requestId, true, true);
}

struct Sample
{
    Poco::Int64 timestamp{0};
    double cpuPercent{0};
    double memoryPercent{0};
    Poco::UInt64 memoryUsedMb{0};
    Poco::UInt64 memoryTotalMb{0};
    double diskPercent{0};
    Poco::UInt64 diskUsedGb{0};
    Poco::UInt64 diskTotalGb{0};
    double networkReceiveKbps{0};
    double networkSendKbps{0};
    Poco::UInt64 threadCount{0};
};

class SystemMonitoringService final : public Poco::OSP::Service, public Poco::Runnable
{
public:
    void start()
    {
        _stopping = false;
        _thread.start(*this);
    }

    void stop()
    {
        _stopping = true;
        if (_thread.isRunning())
            _thread.join();
    }

    void run() override
    {
        while (!_stopping)
        {
            const Sample sample = collect();
            auto& metrics = PocoDDS::Observability::Metrics::global();
            metrics.recordHistogram("system.cpu.utilization", sample.cpuPercent / 100.0, {},
                             "Host CPU utilization", "1");
            metrics.recordHistogram("system.memory.utilization", sample.memoryPercent / 100.0, {},
                             "Host memory utilization", "1");
            metrics.recordHistogram("system.memory.usage", static_cast<double>(sample.memoryUsedMb), {},
                             "Host physical memory used", "MiBy");
            metrics.recordHistogram("system.filesystem.utilization", sample.diskPercent / 100.0,
                             {{"mountpoint", "."}}, "Runtime filesystem utilization", "1");
            metrics.recordHistogram("system.network.io", sample.networkReceiveKbps,
                             {{"direction", "receive"}}, "Host network throughput", "KiBy/s");
            metrics.recordHistogram("system.network.io", sample.networkSendKbps,
                             {{"direction", "transmit"}}, "Host network throughput", "KiBy/s");
            metrics.recordHistogram("process.thread.count", static_cast<double>(sample.threadCount), {},
                             "Runtime process thread count", "{thread}");
            {
                Poco::FastMutex::ScopedLock lock(_mutex);
                _history.push_back(sample);
                while (_history.size() > 60)
                    _history.pop_front();
            }
            for (int wait = 0; wait < 10 && !_stopping; ++wait)
                Poco::Thread::sleep(100);
        }
    }

    std::deque<Sample> history() const
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        return _history;
    }

    const std::type_info& type() const override { return typeid(SystemMonitoringService); }
    bool isA(const std::type_info& other) const override
    {
        return other == typeid(SystemMonitoringService) || Poco::OSP::Service::isA(other);
    }

private:
    Sample collect()
    {
        Sample result;
        result.timestamp = Poco::Timestamp().epochMicroseconds() / 1000;
        collectCpu(result);
        collectMemory(result);
        collectDisk(result);
        collectNetwork(result);
        collectThreads(result);
        return result;
    }

    void collectDisk(Sample& sample)
    {
        try
        {
            Poco::File current(".");
            const Poco::UInt64 total = current.totalSpace();
            const Poco::UInt64 free = current.usableSpace();
            if (total)
            {
                const Poco::UInt64 used = total - free;
                sample.diskPercent =
                    100.0 * static_cast<double>(used) / static_cast<double>(total);
                sample.diskUsedGb = used / (1024ULL * 1024ULL * 1024ULL);
                sample.diskTotalGb = total / (1024ULL * 1024ULL * 1024ULL);
            }
        }
        catch (...) {}
    }

#if defined(POCO_OS_FAMILY_WINDOWS)
    static Poco::UInt64 fileTimeValue(const FILETIME& value)
    {
        return (static_cast<Poco::UInt64>(value.dwHighDateTime) << 32) |
            value.dwLowDateTime;
    }

    void collectCpu(Sample& sample)
    {
        FILETIME idleTime;
        FILETIME kernelTime;
        FILETIME userTime;
        if (!GetSystemTimes(&idleTime, &kernelTime, &userTime))
            return;
        const Poco::UInt64 idle = fileTimeValue(idleTime);
        const Poco::UInt64 kernel = fileTimeValue(kernelTime);
        const Poco::UInt64 user = fileTimeValue(userTime);
        const Poco::UInt64 totalDelta = (kernel - _previousKernel) + (user - _previousUser);
        const Poco::UInt64 idleDelta = idle - _previousIdle;
        if (_previousKernel && totalDelta)
            sample.cpuPercent = 100.0 * static_cast<double>(totalDelta - idleDelta) /
                static_cast<double>(totalDelta);
        _previousIdle = idle;
        _previousKernel = kernel;
        _previousUser = user;
    }

    void collectMemory(Sample& sample)
    {
        MEMORYSTATUSEX status{};
        status.dwLength = sizeof(status);
        if (!GlobalMemoryStatusEx(&status))
            return;
        sample.memoryPercent = static_cast<double>(status.dwMemoryLoad);
        sample.memoryTotalMb = status.ullTotalPhys / (1024ULL * 1024ULL);
        sample.memoryUsedMb =
            (status.ullTotalPhys - status.ullAvailPhys) / (1024ULL * 1024ULL);
    }

    void collectNetwork(Sample& sample)
    {
        MIB_IF_TABLE2* table = nullptr;
        if (GetIfTable2(&table) != NO_ERROR)
            return;
        Poco::UInt64 received = 0;
        Poco::UInt64 sent = 0;
        for (ULONG index = 0; index < table->NumEntries; ++index)
        {
            const auto& row = table->Table[index];
            if (row.OperStatus == IfOperStatusUp &&
                row.Type != IF_TYPE_SOFTWARE_LOOPBACK)
            {
                received += row.InOctets;
                sent += row.OutOctets;
            }
        }
        FreeMibTable(table);
        calculateNetworkRates(sample, received, sent);
    }

    void collectThreads(Sample& sample)
    {
        HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        if (snapshot == INVALID_HANDLE_VALUE)
            return;
        THREADENTRY32 entry{};
        entry.dwSize = sizeof(entry);
        if (Thread32First(snapshot, &entry))
        {
            do
            {
                if (entry.th32OwnerProcessID == GetCurrentProcessId())
                    ++sample.threadCount;
            }
            while (Thread32Next(snapshot, &entry));
        }
        CloseHandle(snapshot);
    }
#else
    void collectCpu(Sample& sample)
    {
        std::ifstream input("/proc/stat");
        std::string name;
        Poco::UInt64 user = 0, nice = 0, system = 0, idle = 0, ioWait = 0;
        if (!(input >> name >> user >> nice >> system >> idle >> ioWait))
            return;
        const Poco::UInt64 total = user + nice + system + idle + ioWait;
        const Poco::UInt64 totalDelta = total - _previousCpuTotal;
        const Poco::UInt64 idleDelta = (idle + ioWait) - _previousCpuIdle;
        if (_previousCpuTotal && totalDelta)
            sample.cpuPercent = 100.0 * static_cast<double>(totalDelta - idleDelta) /
                static_cast<double>(totalDelta);
        _previousCpuTotal = total;
        _previousCpuIdle = idle + ioWait;
    }

    void collectMemory(Sample& sample)
    {
        struct sysinfo info {};
        if (sysinfo(&info) != 0)
            return;
        const Poco::UInt64 total = info.totalram * info.mem_unit;
        const Poco::UInt64 free = (info.freeram + info.bufferram) * info.mem_unit;
        sample.memoryTotalMb = total / (1024ULL * 1024ULL);
        sample.memoryUsedMb = (total - free) / (1024ULL * 1024ULL);
        if (total)
            sample.memoryPercent =
                100.0 * static_cast<double>(total - free) / static_cast<double>(total);
    }

    void collectNetwork(Sample& sample)
    {
        std::ifstream input("/proc/net/dev");
        std::string line;
        Poco::UInt64 received = 0;
        Poco::UInt64 sent = 0;
        while (std::getline(input, line))
        {
            const auto colon = line.find(':');
            if (colon == std::string::npos)
                continue;
            std::string interfaceName = line.substr(0, colon);
            interfaceName.erase(
                std::remove_if(interfaceName.begin(), interfaceName.end(), ::isspace),
                interfaceName.end());
            if (interfaceName == "lo")
                continue;
            std::istringstream fields(line.substr(colon + 1));
            Poco::UInt64 receiveBytes = 0;
            Poco::UInt64 sendBytes = 0;
            Poco::UInt64 ignored = 0;
            fields >> receiveBytes;
            for (int index = 0; index < 7; ++index) fields >> ignored;
            fields >> sendBytes;
            received += receiveBytes;
            sent += sendBytes;
        }
        calculateNetworkRates(sample, received, sent);
    }

    void collectThreads(Sample& sample)
    {
        std::ifstream input("/proc/self/status");
        std::string key;
        while (input >> key)
        {
            if (key == "Threads:")
            {
                input >> sample.threadCount;
                return;
            }
            std::string ignored;
            std::getline(input, ignored);
        }
    }
#endif

    void calculateNetworkRates(Sample& sample, Poco::UInt64 received, Poco::UInt64 sent)
    {
        const Poco::Timestamp now;
        if (_previousNetworkTime.epochMicroseconds() != 0)
        {
            const double seconds =
                static_cast<double>(now - _previousNetworkTime) / 1000000.0;
            if (seconds > 0 && received >= _previousReceived && sent >= _previousSent)
            {
                sample.networkReceiveKbps =
                    static_cast<double>(received - _previousReceived) / 1024.0 / seconds;
                sample.networkSendKbps =
                    static_cast<double>(sent - _previousSent) / 1024.0 / seconds;
            }
        }
        _previousReceived = received;
        _previousSent = sent;
        _previousNetworkTime = now;
    }

    mutable Poco::FastMutex _mutex;
    std::deque<Sample> _history;
    std::atomic<bool> _stopping{false};
    Poco::Thread _thread{"SystemMonitoring"};
    Poco::UInt64 _previousIdle{0};
    Poco::UInt64 _previousKernel{0};
    Poco::UInt64 _previousUser{0};
    Poco::UInt64 _previousCpuTotal{0};
    Poco::UInt64 _previousCpuIdle{0};
    Poco::UInt64 _previousReceived{0};
    Poco::UInt64 _previousSent{0};
    Poco::Timestamp _previousNetworkTime{0};
};

Poco::JSON::Object::Ptr sampleJson(const Sample& sample)
{
    auto result = new Poco::JSON::Object;
    result->set("timestamp", sample.timestamp);
    result->set("cpuPercent", sample.cpuPercent);
    result->set("memoryPercent", sample.memoryPercent);
    result->set("memoryUsedMb", sample.memoryUsedMb);
    result->set("memoryTotalMb", sample.memoryTotalMb);
    result->set("diskPercent", sample.diskPercent);
    result->set("diskUsedGb", sample.diskUsedGb);
    result->set("diskTotalGb", sample.diskTotalGb);
    result->set("networkReceiveKbps", sample.networkReceiveKbps);
    result->set("networkSendKbps", sample.networkSendKbps);
    result->set("threadCount", sample.threadCount);
    return result;
}

class MetricsHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit MetricsHandler(Poco::OSP::BundleContext::Ptr context) : _context(context) {}

    void handleRequest(Poco::Net::HTTPServerRequest&,
                       Poco::Net::HTTPServerResponse& response) override
    {
        auto serviceRef = _context->registry().findByName(SERVICE_NAME);
        if (!serviceRef)
        {
            response.setStatus(Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE);
            response.send() << "{\"error\":\"system monitoring service unavailable\"}";
            return;
        }
        auto service = serviceRef->castedInstance<SystemMonitoringService>();
        const auto history = service->history();
        Poco::JSON::Array::Ptr samples = new Poco::JSON::Array;
        for (const auto& sample : history)
            samples->add(sampleJson(sample));
        Poco::JSON::Object root;
        root.set("host", Poco::Environment::nodeName());
        root.set("intervalMilliseconds", 1000);
        root.set("samples", samples);
        if (!history.empty())
            root.set("current", sampleJson(history.back()));
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json");
        root.stringify(response.send());
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};

class OpenTelemetryMetricsHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest&,
                       Poco::Net::HTTPServerResponse& response) override
    {
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        response.send() << PocoDDS::Observability::Metrics::global().snapshotJson();
    }
};

struct DiagnosticEvent
{
    std::string traceId;
    std::string domain;
    std::string instance;
    std::string event;
    PocoDDS::Reliability::Failure failure;
    long long observedAtMicroseconds{0};
};

struct AlertPolicy
{
    long long debounceMicroseconds{0};
    long long escalationMicroseconds{300000000};
    std::size_t retention{500};
    std::vector<std::string> silencedCodes;
};

struct AlertRecord
{
    std::string id;
    std::string domain;
    std::string instance;
    std::string code;
    std::string status{"pending"};
    std::string severity{"warning"};
    std::string traceId;
    std::string message;
    bool retryable{false};
    bool silenced{false};
    bool notified{false};
    bool suppressedByDebounce{false};
    long long firstSeenMicroseconds{0};
    long long lastSeenMicroseconds{0};
    long long resolvedAtMicroseconds{0};
    std::size_t observations{0};
};

struct AlertSinkDeliveryStatus
{
    std::uint64_t successes{0};
    std::uint64_t failures{0};
    std::uint64_t dropped{0};
    std::uint64_t circuitOpenSkips{0};
    std::uint64_t consecutiveFailures{0};
    long long lastSuccessMicroseconds{0};
    long long lastFailureMicroseconds{0};
    long long circuitOpenUntilMicroseconds{0};
    std::size_t queueDepth{0};
    bool delivering{false};
    std::string lastError;
};

class AlertDispatcher
{
public:
    void start(Poco::OSP::BundleContext::Ptr context, std::size_t capacity,
               std::uint64_t failureThreshold, long long circuitOpenMicroseconds)
    {
        {
            std::lock_guard<std::mutex> lock(_mutex);
            _context = context;
            _capacity = std::max<std::size_t>(1, capacity);
            _failureThreshold = std::max<std::uint64_t>(1, failureThreshold);
            _circuitOpenMicroseconds = std::max<long long>(1000, circuitOpenMicroseconds);
            _running = true;
        }
        auto listener = context->registry().createListener(
            "pdr.alertSink",
            Poco::delegate(this, &AlertDispatcher::onSinkRegistered),
            Poco::delegate(this, &AlertDispatcher::onSinkUnregistered));
        std::lock_guard<std::mutex> lock(_mutex);
        if (_running) _listener = std::move(listener);
    }

    void stop()
    {
        std::vector<std::shared_ptr<class SinkChannel>> channels;
        {
            std::lock_guard<std::mutex> lock(_mutex);
            _running = false;
            _listener = nullptr;
            for (const auto& entry : _channels) channels.push_back(entry.second);
            channels.insert(channels.end(), _retiredChannels.begin(), _retiredChannels.end());
            _channels.clear();
            _retiredChannels.clear();
            _context = nullptr;
        }
        for (const auto& channel : channels) channel->stop();
    }

    void enqueue(PocoDDS::Reliability::AlertNotification notification)
    {
        std::vector<std::shared_ptr<SinkChannel>> channels;
        {
            std::lock_guard<std::mutex> lock(_mutex);
            if (!_running) return;
            reapRetiredChannels();
            channels.reserve(_channels.size());
            for (const auto& entry : _channels) channels.push_back(entry.second);
        }
        for (const auto& channel : channels) channel->enqueue(notification);
    }

    AlertSinkDeliveryStatus status(const std::string& serviceName)
    {
        std::shared_ptr<SinkChannel> channel;
        {
            std::lock_guard<std::mutex> lock(_mutex);
            const auto iterator = _channels.find(serviceName);
            if (iterator == _channels.end()) return {};
            channel = iterator->second;
        }
        return channel->status();
    }

private:
    static long long nowMicroseconds()
    {
        return std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
    }

    class SinkChannel
    {
    public:
        SinkChannel(Poco::OSP::BundleContext::Ptr context,
                    Poco::OSP::ServiceRef::Ptr service, std::size_t capacity,
                    std::uint64_t failureThreshold, long long circuitOpenMicroseconds):
            _context(std::move(context)), _service(std::move(service)),
            _capacity(capacity), _failureThreshold(failureThreshold),
            _circuitOpenMicroseconds(circuitOpenMicroseconds),
            _sinkName(_service->properties().get("pdr.alertSink.name", _service->name())),
            _receiveSilenced(_service->properties().getBool(
                "pdr.alertSink.receiveSilenced", false)),
            _worker([this] { run(); })
        {
        }

        ~SinkChannel()
        {
            stop();
        }

        bool matches(const Poco::OSP::ServiceRef::Ptr& service) const
        {
            return _service.get() == service.get();
        }

        bool finished() const
        {
            return _finished.load();
        }

        void enqueue(const PocoDDS::Reliability::AlertNotification& notification)
        {
            if (notification.silenced && !_receiveSilenced) return;
            std::lock_guard<std::mutex> lock(_mutex);
            if (!_running) return;
            if (_queue.size() >= _capacity)
            {
                ++_status.dropped;
                PocoDDS::Observability::Metrics::global().addCounter(
                    "pdr.alert.delivery", 1,
                    {{"result", "dropped"}, {"sink", _sinkName}});
                return;
            }
            _queue.push_back(notification);
            _condition.notify_one();
        }

        AlertSinkDeliveryStatus status() const
        {
            std::lock_guard<std::mutex> lock(_mutex);
            auto value = _status;
            value.queueDepth = _queue.size();
            value.delivering = _delivering;
            return value;
        }

        void stop()
        {
            requestStop();
            if (_worker.joinable()) _worker.join();
        }

        void requestStop()
        {
            {
                std::lock_guard<std::mutex> lock(_mutex);
                if (!_running) return;
                _running = false;
                _status.dropped += _queue.size();
                _queue.clear();
            }
            _condition.notify_all();
        }

    private:
        long long circuitOpenDelayMicroseconds()
        {
            std::lock_guard<std::mutex> lock(_mutex);
            const auto delay = _status.circuitOpenUntilMicroseconds - nowMicroseconds();
            if (delay <= 0) return 0;
            ++_status.circuitOpenSkips;
            return delay;
        }

        void recordSuccess()
        {
            std::lock_guard<std::mutex> lock(_mutex);
            ++_status.successes;
            _status.consecutiveFailures = 0;
            _status.lastSuccessMicroseconds = nowMicroseconds();
            _status.circuitOpenUntilMicroseconds = 0;
            _status.lastError.clear();
        }

        void recordFailure(const std::string& error)
        {
            std::lock_guard<std::mutex> lock(_mutex);
            ++_status.failures;
            ++_status.consecutiveFailures;
            _status.lastFailureMicroseconds = nowMicroseconds();
            _status.lastError = error;
            if (_status.consecutiveFailures >= _failureThreshold)
                _status.circuitOpenUntilMicroseconds =
                    _status.lastFailureMicroseconds + _circuitOpenMicroseconds;
        }

        void run()
        {
            for (;;)
            {
                PocoDDS::Reliability::AlertNotification notification;
                {
                    std::unique_lock<std::mutex> lock(_mutex);
                    _condition.wait(lock, [this] { return !_running || !_queue.empty(); });
                    if (!_running)
                    {
                        _finished = true;
                        return;
                    }
                    notification = std::move(_queue.front());
                    _queue.pop_front();
                    _delivering = true;
                }
                const auto circuitDelay = circuitOpenDelayMicroseconds();
                if (circuitDelay > 0)
                {
                    PocoDDS::Observability::Metrics::global().addCounter(
                        "pdr.alert.delivery", 1,
                        {{"result", "circuit_open"}, {"sink", _sinkName}});
                    std::unique_lock<std::mutex> lock(_mutex);
                    if (_condition.wait_for(lock, std::chrono::microseconds(circuitDelay),
                                            [this] { return !_running; }))
                    {
                        _delivering = false;
                        _finished = true;
                        return;
                    }
                }
                try
                {
                    auto instance = _service->instance();
                    auto* sink = dynamic_cast<PocoDDS::Reliability::AlertSink*>(instance.get());
                    if (!sink) throw Poco::BadCastException("service does not implement AlertSink");
                    sink->deliver(notification);
                    recordSuccess();
                    PocoDDS::Observability::Metrics::global().addCounter(
                        "pdr.alert.delivery", 1,
                        {{"result", "success"}, {"sink", _sinkName}});
                }
                catch (const Poco::Exception& exception)
                {
                    recordFailure(exception.displayText());
                    _context->logger().error(
                        "Alert sink " + _sinkName + " failed: " + exception.displayText());
                    PocoDDS::Observability::Metrics::global().addCounter(
                        "pdr.alert.delivery", 1,
                        {{"result", "error"}, {"sink", _sinkName}});
                }
                catch (const std::exception& exception)
                {
                    recordFailure(exception.what());
                    _context->logger().error(
                        "Alert sink " + _sinkName + " failed: " + exception.what());
                    PocoDDS::Observability::Metrics::global().addCounter(
                        "pdr.alert.delivery", 1,
                        {{"result", "error"}, {"sink", _sinkName}});
                }
                std::lock_guard<std::mutex> lock(_mutex);
                _delivering = false;
            }
        }

        Poco::OSP::BundleContext::Ptr _context;
        Poco::OSP::ServiceRef::Ptr _service;
        const std::size_t _capacity;
        const std::uint64_t _failureThreshold;
        const long long _circuitOpenMicroseconds;
        const std::string _sinkName;
        const bool _receiveSilenced;
        mutable std::mutex _mutex;
        std::condition_variable _condition;
        std::deque<PocoDDS::Reliability::AlertNotification> _queue;
        AlertSinkDeliveryStatus _status;
        bool _running{true};
        bool _delivering{false};
        std::atomic<bool> _finished{false};
        std::thread _worker;
    };

    void onSinkRegistered(const Poco::OSP::ServiceRef::Ptr& service)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (!_running || !_context) return;
        const auto existing = _channels.find(service->name());
        if (existing != _channels.end())
        {
            if (existing->second->matches(service)) return;
            existing->second->requestStop();
            _retiredChannels.push_back(existing->second);
            _channels.erase(existing);
        }
        _channels.emplace(service->name(), std::make_shared<SinkChannel>(
            _context, service, _capacity, _failureThreshold, _circuitOpenMicroseconds));
        reapRetiredChannels();
    }

    void onSinkUnregistered(const Poco::OSP::ServiceRef::Ptr& service)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        const auto iterator = _channels.find(service->name());
        if (iterator == _channels.end() || !iterator->second->matches(service)) return;
        iterator->second->requestStop();
        _retiredChannels.push_back(iterator->second);
        _channels.erase(iterator);
        reapRetiredChannels();
    }

    void reapRetiredChannels()
    {
        for (auto iterator = _retiredChannels.begin();
             iterator != _retiredChannels.end();)
        {
            if ((*iterator)->finished())
            {
                (*iterator)->stop();
                iterator = _retiredChannels.erase(iterator);
            }
            else ++iterator;
        }
    }

    std::mutex _mutex;
    Poco::OSP::BundleContext::Ptr _context;
    Poco::OSP::ServiceListener::Ptr _listener;
    std::unordered_map<std::string, std::shared_ptr<SinkChannel>> _channels;
    std::vector<std::shared_ptr<SinkChannel>> _retiredChannels;
    std::size_t _capacity{1000};
    std::uint64_t _failureThreshold{5};
    long long _circuitOpenMicroseconds{30000000};
    bool _running{false};
};

AlertDispatcher& alertDispatcher()
{
    static AlertDispatcher dispatcher;
    return dispatcher;
}

class JsonlAlertSinkService final : public Poco::OSP::Service,
                                    public PocoDDS::Reliability::AlertSink
{
public:
    JsonlAlertSinkService(std::string path, std::size_t maximumBytes):
        _path(std::move(path)), _maximumBytes(std::max<std::size_t>(1024, maximumBytes))
    {
        Poco::File(Poco::Path(_path).parent()).createDirectories();
    }

    void deliver(const PocoDDS::Reliability::AlertNotification& value) override
    {
        Poco::JSON::Object object;
        object.set("alertId", value.alertId);
        object.set("event", value.event);
        object.set("domain", value.domain);
        object.set("instance", value.instance);
        object.set("code", value.code);
        object.set("status", value.status);
        object.set("severity", value.severity);
        object.set("traceId", value.traceId);
        object.set("message", value.message);
        object.set("retryable", value.retryable);
        object.set("silenced", value.silenced);
        object.set("occurredAtMicroseconds", value.occurredAtMicroseconds);
        std::ostringstream line;
        object.stringify(line);
        std::lock_guard<std::mutex> lock(_mutex);
        rotateIfRequired(line.str().size() + 1);
        Poco::FileOutputStream stream(_path, std::ios::app);
        stream << line.str() << '\n';
        stream.close();
        if (!stream.good()) throw Poco::WriteFileException(_path);
    }

    std::vector<Poco::JSON::Object::Ptr> recent(std::size_t limit) const
    {
        std::lock_guard<std::mutex> lock(_mutex);
        std::vector<Poco::JSON::Object::Ptr> result;
        if (!Poco::File(_path).exists()) return result;
        std::ifstream stream(_path);
        std::deque<Poco::JSON::Object::Ptr> tail;
        std::string line;
        while (std::getline(stream, line))
        {
            try
            {
                auto parsed = Poco::JSON::Parser().parse(line).extract<Poco::JSON::Object::Ptr>();
                tail.push_back(parsed);
                if (tail.size() > limit) tail.pop_front();
            }
            catch (...) {}
        }
        for (auto it = tail.rbegin(); it != tail.rend(); ++it) result.push_back(*it);
        return result;
    }

    const std::string& path() const noexcept { return _path; }
    const std::type_info& type() const override { return typeid(JsonlAlertSinkService); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(JsonlAlertSinkService).name() ||
               Poco::OSP::Service::isA(other);
    }

private:
    void rotateIfRequired(std::size_t incoming)
    {
        Poco::File file(_path);
        if (!file.exists() || file.getSize() + incoming <= _maximumBytes) return;
        Poco::File archive(_path + ".1");
        if (archive.exists()) archive.remove();
        file.renameTo(archive.path());
    }

    std::string _path;
    std::size_t _maximumBytes;
    mutable std::mutex _mutex;
};

class DiagnosticEventTracker
{
public:
    void configure(AlertPolicy policy)
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _policy = std::move(policy);
    }

    void observe(Poco::Logger& logger, const std::string& domain,
                 const std::string& instance,
                 const PocoDDS::Reliability::Failure& failure)
    {
        if (failure.code.empty()) return;
        const std::string key = domain + ":" + instance;
        std::lock_guard<std::mutex> lock(_mutex);
        updateAlert(logger, key, domain, instance, failure);
        const auto found = _states.find(key);
        if (found != _states.end() && found->second.code == failure.code &&
            found->second.active == failure.active &&
            found->second.occurredAtMicroseconds == failure.occurredAtMicroseconds)
            return;
        const bool resolving = !failure.active && found != _states.end() && found->second.active;
        _states[key] = failure;
        if (!failure.active && !resolving) return;

        DiagnosticEvent event;
        event.traceId = nextTraceId();
        event.domain = domain;
        event.instance = instance;
        event.event = failure.active ? "failure.detected" : "failure.resolved";
        event.failure = failure;
        event.observedAtMicroseconds = nowMicroseconds();
        _events.push_front(event);
        if (_events.size() > 500) _events.pop_back();

        const std::string log =
            "diagnostic.event=" + event.event + " domain=" + domain +
            " instance=" + instance + " error.code=" + failure.code +
            " error.category=" + PocoDDS::Reliability::toString(failure.kind) +
            " error.retryable=" + (failure.retryable ? "true" : "false") +
            " traceId=" + event.traceId;
        if (failure.active) logger.warning(log);
        else logger.information(log);

        PocoDDS::Observability::SpanSnapshot span;
        span.businessName = "runtime.diagnostics";
        span.businessInstanceId = key;
        span.operation = event.event;
        span.serviceName = "pdr-runtime";
        span.bundleName = "pdr.platform.systemMonitoring";
        span.hostName = Poco::Environment::nodeName();
        span.processId = Poco::Process::id();
        span.traceId = event.traceId;
        span.spanId = event.traceId.substr(16, 16);
        span.status = failure.active ? "failed" : "success";
        span.errorCode = failure.code;
        span.errorMessage = failure.message;
        span.startedUnixMicroseconds = event.observedAtMicroseconds;
        span.endedUnixMicroseconds = event.observedAtMicroseconds;
        span.inputs = {{"domain", domain}, {"instance", instance}};
        span.outputs = {{"active", failure.active ? "true" : "false"},
                        {"category", PocoDDS::Reliability::toString(failure.kind)},
                        {"retryable", failure.retryable ? "true" : "false"}};
        span.logs.push_back({event.observedAtMicroseconds,
                             failure.active ? "error" : "info",
                             event.event,
                             {{"error.code", failure.code},
                              {"domain", domain}, {"instance", instance}}});
        PocoDDS::Observability::globalTraceStore().upsert(span);
    }

    std::vector<DiagnosticEvent> events() const
    {
        std::lock_guard<std::mutex> lock(_mutex);
        return {_events.begin(), _events.end()};
    }

    std::vector<AlertRecord> alerts() const
    {
        std::lock_guard<std::mutex> lock(_mutex);
        std::vector<AlertRecord> result;
        result.reserve(_alerts.size());
        for (const auto& key : _alertOrder)
        {
            const auto found = _alerts.find(key);
            if (found != _alerts.end()) result.push_back(found->second);
        }
        return result;
    }

    AlertPolicy policy() const
    {
        std::lock_guard<std::mutex> lock(_mutex);
        return _policy;
    }

private:
    bool isSilenced(const std::string& code) const
    {
        return std::any_of(_policy.silencedCodes.begin(), _policy.silencedCodes.end(),
            [&code](const auto& pattern) {
                return !pattern.empty() &&
                    (pattern.back() == '*'
                        ? code.rfind(pattern.substr(0, pattern.size() - 1), 0) == 0
                        : code == pattern);
            });
    }

    void emitAlert(Poco::Logger& logger, const std::string& event,
                   const AlertRecord& alert)
    {
        const std::string message =
            "alert.event=" + event + " alert.id=" + alert.id +
            " domain=" + alert.domain + " instance=" + alert.instance +
            " error.code=" + alert.code + " alert.status=" + alert.status +
            " alert.severity=" + alert.severity +
            " alert.silenced=" + (alert.silenced ? "true" : "false") +
            " traceId=" + alert.traceId;
        if (event == "alert.resolved") logger.information(message);
        else logger.warning(message);
        PocoDDS::Observability::Metrics::global().addCounter(
            "pdr.alert.transitions", 1,
            {{"event", event}, {"severity", alert.severity},
             {"domain", alert.domain}, {"silenced", alert.silenced ? "true" : "false"}});
        PocoDDS::Observability::SpanSnapshot span;
        span.businessName = "runtime.alerts";
        span.businessInstanceId = alert.domain + ":" + alert.instance;
        span.operation = event;
        span.serviceName = "pdr-runtime";
        span.bundleName = "pdr.platform.systemMonitoring";
        span.hostName = Poco::Environment::nodeName();
        span.processId = Poco::Process::id();
        span.traceId = alert.traceId;
        span.spanId = alert.traceId.substr(16, 16);
        span.status = event == "alert.resolved" ? "success" : "failed";
        span.errorCode = alert.code;
        span.errorMessage = alert.message;
        span.startedUnixMicroseconds = alert.firstSeenMicroseconds;
        span.endedUnixMicroseconds = alert.lastSeenMicroseconds;
        span.inputs = {{"domain", alert.domain}, {"instance", alert.instance},
                       {"silenced", alert.silenced ? "true" : "false"}};
        span.outputs = {{"status", alert.status}, {"severity", alert.severity},
                        {"observations", std::to_string(alert.observations)}};
        span.logs.push_back({alert.lastSeenMicroseconds,
                             event == "alert.resolved" ? "info" : "warning",
                             event, {{"error.code", alert.code},
                                     {"severity", alert.severity}}});
        PocoDDS::Observability::globalTraceStore().upsert(span);
        alertDispatcher().enqueue({alert.id, event, alert.domain, alert.instance,
            alert.code, alert.status, alert.severity, alert.traceId, alert.message,
            alert.retryable, alert.silenced, alert.lastSeenMicroseconds});
    }

    void updateAlert(Poco::Logger& logger, const std::string& key,
                     const std::string& domain, const std::string& instance,
                     const PocoDDS::Reliability::Failure& failure)
    {
        const auto now = nowMicroseconds();
        auto found = _alerts.find(key);
        if (failure.active)
        {
            if (found == _alerts.end() || found->second.status == "resolved" ||
                found->second.code != failure.code)
            {
                AlertRecord alert;
                alert.id = nextTraceId();
                alert.traceId = alert.id;
                alert.domain = domain;
                alert.instance = instance;
                alert.code = failure.code;
                alert.message = failure.message;
                alert.retryable = failure.retryable;
                alert.silenced = isSilenced(failure.code);
                alert.firstSeenMicroseconds = now;
                alert.lastSeenMicroseconds = now;
                alert.observations = 1;
                _alerts[key] = alert;
                _alertOrder.erase(std::remove(_alertOrder.begin(), _alertOrder.end(), key),
                                  _alertOrder.end());
                _alertOrder.push_front(key);
                found = _alerts.find(key);
            }
            else
            {
                found->second.lastSeenMicroseconds = now;
                ++found->second.observations;
            }
            auto& alert = found->second;
            if (alert.status == "pending" &&
                now - alert.firstSeenMicroseconds >= _policy.debounceMicroseconds)
            {
                alert.status = alert.silenced ? "silenced" : "firing";
                alert.notified = true;
                emitAlert(logger, "alert.opened", alert);
            }
            if ((alert.status == "firing" || alert.status == "silenced") &&
                alert.severity != "critical" && _policy.escalationMicroseconds >= 0 &&
                now - alert.firstSeenMicroseconds >= _policy.escalationMicroseconds)
            {
                alert.severity = "critical";
                emitAlert(logger, "alert.escalated", alert);
            }
        }
        else if (found != _alerts.end() && found->second.status != "resolved")
        {
            auto& alert = found->second;
            const bool wasNotified = alert.status != "pending";
            alert.suppressedByDebounce = !wasNotified;
            alert.status = "resolved";
            alert.lastSeenMicroseconds = now;
            alert.resolvedAtMicroseconds = now;
            if (wasNotified) emitAlert(logger, "alert.resolved", alert);
        }
        while (_alertOrder.size() > _policy.retention)
        {
            _alerts.erase(_alertOrder.back());
            _alertOrder.pop_back();
        }
    }

    static long long nowMicroseconds()
    {
        return std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
    }

    static std::string nextTraceId()
    {
        static std::atomic<std::uint64_t> sequence{0};
        std::ostringstream value;
        value << std::hex << std::setfill('0')
              << std::setw(16) << static_cast<std::uint64_t>(nowMicroseconds())
              << std::setw(16) << ++sequence;
        return value.str();
    }

    mutable std::mutex _mutex;
    std::unordered_map<std::string, PocoDDS::Reliability::Failure> _states;
    std::deque<DiagnosticEvent> _events;
    AlertPolicy _policy;
    std::unordered_map<std::string, AlertRecord> _alerts;
    std::deque<std::string> _alertOrder;
};

DiagnosticEventTracker& diagnosticEvents()
{
    static DiagnosticEventTracker tracker;
    return tracker;
}

class DiagnosticEventsHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest&,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Poco::JSON::Array::Ptr events = new Poco::JSON::Array;
        for (const auto& event : diagnosticEvents().events())
        {
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("traceId", event.traceId);
            item->set("domain", event.domain);
            item->set("instance", event.instance);
            item->set("event", event.event);
            item->set("code", event.failure.code);
            item->set("category", PocoDDS::Reliability::toString(event.failure.kind));
            item->set("retryable", event.failure.retryable);
            item->set("active", event.failure.active);
            item->set("message", event.failure.message);
            item->set("occurredAtMicroseconds", event.failure.occurredAtMicroseconds);
            item->set("observedAtMicroseconds", event.observedAtMicroseconds);
            events->add(item);
        }
        Poco::JSON::Object root;
        root.set("schemaVersion", 1);
        root.set("count", events->size());
        root.set("events", events);
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }
};

class AlertsHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest&,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Poco::JSON::Array::Ptr alerts = new Poco::JSON::Array;
        for (const auto& alert : diagnosticEvents().alerts())
        {
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("id", alert.id);
            item->set("domain", alert.domain);
            item->set("instance", alert.instance);
            item->set("code", alert.code);
            item->set("status", alert.status);
            item->set("severity", alert.severity);
            item->set("traceId", alert.traceId);
            item->set("message", alert.message);
            item->set("retryable", alert.retryable);
            item->set("silenced", alert.silenced);
            item->set("notified", alert.notified);
            item->set("suppressedByDebounce", alert.suppressedByDebounce);
            item->set("firstSeenMicroseconds", alert.firstSeenMicroseconds);
            item->set("lastSeenMicroseconds", alert.lastSeenMicroseconds);
            item->set("resolvedAtMicroseconds", alert.resolvedAtMicroseconds);
            item->set("observations", static_cast<Poco::UInt64>(alert.observations));
            alerts->add(item);
        }
        const auto policy = diagnosticEvents().policy();
        Poco::JSON::Array::Ptr silencedCodes = new Poco::JSON::Array;
        for (const auto& code : policy.silencedCodes) silencedCodes->add(code);
        Poco::JSON::Object::Ptr policyJson = new Poco::JSON::Object;
        policyJson->set("debounceMilliseconds", policy.debounceMicroseconds / 1000);
        policyJson->set("escalationMilliseconds", policy.escalationMicroseconds / 1000);
        policyJson->set("retention", static_cast<Poco::UInt64>(policy.retention));
        policyJson->set("silencedCodes", silencedCodes);
        Poco::JSON::Object root;
        root.set("schemaVersion", 1);
        root.set("count", alerts->size());
        root.set("policy", policyJson);
        root.set("alerts", alerts);
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }
};

class AlertHistoryHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit AlertHistoryHandler(Poco::OSP::BundleContext::Ptr context):
        _context(std::move(context)) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        std::size_t limit = 100;
        for (const auto& parameter : Poco::URI(request.getURI()).getQueryParameters())
            if (parameter.first == "limit")
            {
                try { limit = static_cast<std::size_t>(Poco::NumberParser::parse(parameter.second)); }
                catch (...) { limit = 100; }
            }
        limit = std::clamp<std::size_t>(limit, 1, 1000);
        Poco::JSON::Array::Ptr records = new Poco::JSON::Array;
        std::string path;
        const auto service = _context->registry().findByName("pdr.alertSink.localHistory");
        if (service)
        {
            const auto sink = service->castedInstance<JsonlAlertSinkService>();
            path = sink->path();
            for (const auto& record : sink->recent(limit)) records->add(record);
        }
        Poco::JSON::Object root;
        root.set("schemaVersion", 1);
        root.set("count", records->size());
        root.set("limit", static_cast<Poco::UInt64>(limit));
        root.set("enabled", static_cast<bool>(service));
        root.set("path", path);
        root.set("records", records);
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};

class AlertSinksHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit AlertSinksHandler(Poco::OSP::BundleContext::Ptr context):
        _context(std::move(context)) {}

    void handleRequest(Poco::Net::HTTPServerRequest&,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Poco::JSON::Array::Ptr sinks = new Poco::JSON::Array;
        auto services = _context->registry().find("pdr.alertSink");
        std::sort(services.begin(), services.end(), [](const auto& left, const auto& right) {
            return left->properties().get("pdr.alertSink.name", left->name()) <
                right->properties().get("pdr.alertSink.name", right->name());
        });
        for (const auto& service : services)
        {
            const auto& properties = service->properties();
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("name", properties.get("pdr.alertSink.name", service->name()));
            item->set("type", properties.get("pdr.alertSink.type", "custom"));
            item->set("service", service->name());
            item->set("receiveSilenced",
                      properties.getBool("pdr.alertSink.receiveSilenced", false));
            item->set("registered", true);
            const auto delivery = alertDispatcher().status(service->name());
            item->set("status", delivery.consecutiveFailures ? "degraded" :
                      delivery.successes ? "healthy" : "idle");
            item->set("successes", static_cast<Poco::UInt64>(delivery.successes));
            item->set("failures", static_cast<Poco::UInt64>(delivery.failures));
            item->set("dropped", static_cast<Poco::UInt64>(delivery.dropped));
            item->set("queueDepth", static_cast<Poco::UInt64>(delivery.queueDepth));
            item->set("delivering", delivery.delivering);
            item->set("circuitOpenSkips",
                      static_cast<Poco::UInt64>(delivery.circuitOpenSkips));
            item->set("consecutiveFailures",
                      static_cast<Poco::UInt64>(delivery.consecutiveFailures));
            item->set("lastSuccessMicroseconds", delivery.lastSuccessMicroseconds);
            item->set("lastFailureMicroseconds", delivery.lastFailureMicroseconds);
            const bool circuitOpen =
                delivery.circuitOpenUntilMicroseconds >
                std::chrono::duration_cast<std::chrono::microseconds>(
                    std::chrono::system_clock::now().time_since_epoch()).count();
            item->set("circuitOpen", circuitOpen);
            item->set("circuitOpenUntilMicroseconds",
                      delivery.circuitOpenUntilMicroseconds);
            if (circuitOpen) item->set("status", "circuit-open");
            item->set("lastError", delivery.lastError);
            sinks->add(item);
        }
        Poco::JSON::Object root;
        root.set("schemaVersion", 1);
        root.set("count", sinks->size());
        root.set("sinks", sinks);
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};

class DevicesHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit DevicesHandler(Poco::OSP::BundleContext::Ptr context) : _context(context) {}

    void handleRequest(Poco::Net::HTTPServerRequest&,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Poco::JSON::Array::Ptr devices = new Poco::JSON::Array;
        auto services = _context->registry().find("pdr.device");
        std::sort(services.begin(), services.end(), [](const auto& left, const auto& right) {
            return left->properties().get("pdr.device", left->name()) <
                right->properties().get("pdr.device", right->name());
        });
        for (const auto& service : services)
        {
            const auto& properties = service->properties();
            auto provider = service->castedInstance<PocoDDS::Devices::DeviceService>();
            PocoDDS::Devices::DeviceSnapshot snapshot;
            PocoDDS::Devices::DeviceDiagnostics details;
            PocoDDS::Reliability::Failure failure;
            bool hasDiagnostics = false;
            try
            {
                snapshot = provider->device().snapshot();
            }
            catch (const std::exception& error)
            {
                snapshot.id = properties.get("pdr.device", service->name());
                snapshot.type = properties.get("pdr.deviceType", "unknown");
                snapshot.state = PocoDDS::Devices::DeviceState::fault;
                PocoDDS::Devices::recordFailure(
                    details, failure, "PDR-DEVICE-SNAPSHOT_FAILED",
                    PocoDDS::Reliability::FailureKind::permanent, false, error.what());
                hasDiagnostics = true;
            }
            try
            {
                if (const auto* diagnostic = dynamic_cast<const PocoDDS::Devices::DiagnosticDevice*>(
                        &provider->device()))
                {
                    details = diagnostic->diagnostics();
                    hasDiagnostics = true;
                }
                if (const auto* diagnostic =
                        dynamic_cast<const PocoDDS::Devices::FailureDiagnosticDevice*>(
                            &provider->device()))
                    failure = diagnostic->failure();
            }
            catch (const std::exception& error)
            {
                snapshot.state = PocoDDS::Devices::DeviceState::fault;
                PocoDDS::Devices::recordFailure(
                    details, failure, "PDR-DEVICE-DIAGNOSTICS_FAILED",
                    PocoDDS::Reliability::FailureKind::permanent, false, error.what());
                hasDiagnostics = true;
            }
            Poco::JSON::Object::Ptr device = new Poco::JSON::Object;
            device->set("id", snapshot.id);
            device->set("type", snapshot.type);
            device->set("state", PocoDDS::Devices::toString(snapshot.state));
            device->set("sequence", snapshot.sequence);
            device->set("timestampMicroseconds", snapshot.timestampMicroseconds);
            device->set("bundle", properties.get("pdr.bundle", ""));
            device->set("service", service->name());
            device->set("required", properties.getBool("pdr.deviceRequired", true));
            if (hasDiagnostics)
            {
                Poco::JSON::Object::Ptr diagnostics = new Poco::JSON::Object;
                diagnostics->set("successfulOperations", details.successfulOperations);
                diagnostics->set("failedOperations", details.failedOperations);
                diagnostics->set("reconnectAttempts", details.reconnectAttempts);
                diagnostics->set("consecutiveFailures", details.consecutiveFailures);
                diagnostics->set("lastSuccessMicroseconds", details.lastSuccessMicroseconds);
                diagnostics->set("lastFailureMicroseconds", details.lastFailureMicroseconds);
                diagnostics->set("lastError", details.lastError);
                if (!failure.code.empty() || !details.lastError.empty())
                {
                    Poco::JSON::Object::Ptr error = new Poco::JSON::Object;
                    error->set("code", failure.code.empty()
                        ? "PDR-DEVICE-UNCLASSIFIED" : failure.code);
                    error->set("category", PocoDDS::Reliability::toString(failure.kind));
                    error->set("retryable", failure.retryable);
                    error->set("active", failure.code.empty() ? !details.lastError.empty()
                                                             : failure.active);
                    error->set("occurredAtMicroseconds", failure.occurredAtMicroseconds);
                    error->set("message", failure.message.empty()
                        ? details.lastError : failure.message);
                    diagnostics->set("failure", error);
                    diagnosticEvents().observe(_context->logger(), "device",
                                               snapshot.id, failure);
                    PocoDDS::Observability::Metrics::global().addCounter(
                        "pdr.diagnostics.failure.samples", 1,
                        {{"domain", "device"}, {"instance", snapshot.id},
                         {"code", failure.code.empty()
                            ? "PDR-DEVICE-UNCLASSIFIED" : failure.code},
                         {"category", PocoDDS::Reliability::toString(failure.kind)},
                         {"active", (failure.code.empty() ? !details.lastError.empty()
                                                          : failure.active) ? "true" : "false"}},
                        "Observed structured diagnostic failures", "{sample}");
                }
                device->set("diagnostics", diagnostics);
            }
            devices->add(device);
        }
        Poco::JSON::Object root;
        root.set("schemaVersion", 1);
        root.set("count", devices->size());
        root.set("devices", devices);
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};

Poco::JSON::Object::Ptr protocolDiagnosticsJson(
    const PocoDDS::Protocols::ProtocolDiagnostics& details,
    const PocoDDS::Reliability::Failure& failure = {})
{
    Poco::JSON::Object::Ptr diagnostics = new Poco::JSON::Object;
    diagnostics->set("successfulOperations", details.successfulOperations);
    diagnostics->set("failedOperations", details.failedOperations);
    diagnostics->set("reconnectAttempts", details.reconnectAttempts);
    diagnostics->set("sentMessages", details.sentMessages);
    diagnostics->set("receivedMessages", details.receivedMessages);
    diagnostics->set("sentBytes", details.sentBytes);
    diagnostics->set("receivedBytes", details.receivedBytes);
    diagnostics->set("timeouts", details.timeouts);
    diagnostics->set("handlerFailures", details.handlerFailures);
    diagnostics->set("lastError", details.lastError);
    if (!failure.code.empty() || !details.lastError.empty())
    {
        Poco::JSON::Object::Ptr error = new Poco::JSON::Object;
        error->set("code", failure.code.empty()
            ? "PDR-PROTOCOL-UNCLASSIFIED" : failure.code);
        error->set("category", PocoDDS::Reliability::toString(failure.kind));
        error->set("retryable", failure.retryable);
        error->set("active", failure.code.empty() ? !details.lastError.empty()
                                                   : failure.active);
        error->set("occurredAtMicroseconds", failure.occurredAtMicroseconds);
        error->set("message", failure.message.empty() ? details.lastError : failure.message);
        diagnostics->set("failure", error);
    }
    return diagnostics;
}

class ProtocolsHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit ProtocolsHandler(Poco::OSP::BundleContext::Ptr context): _context(context) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        if (request.getMethod() == Poco::Net::HTTPRequest::HTTP_POST)
        {
            std::string principal;
            if (!managementAuthorized(request, response, "protocol.manage", &principal,
                                      "protocol-lifecycle")) return;
            return handleLifecycle(request, response, principal);
        }
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
            return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                                 "protocol endpoint only supports GET and POST");

        Poco::JSON::Array::Ptr protocols = new Poco::JSON::Array;
        auto services = _context->registry().find("pdr.protocol");
        std::sort(services.begin(), services.end(), [](const auto& left, const auto& right) {
            return left->properties().get("pdr.protocol.id", left->name()) <
                right->properties().get("pdr.protocol.id", right->name());
        });
        for (const auto& service : services)
        {
            const auto& properties = service->properties();
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("id", properties.get("pdr.protocol.id", service->name()));
            item->set("type", properties.get("pdr.protocol.type", "unknown"));
            item->set("bundle", properties.get("pdr.bundle", ""));
            item->set("service", service->name());
            item->set("required", properties.getBool("pdr.protocol.required", false));
            item->set("autoReconnect",
                      properties.getBool("pdr.protocol.autoReconnect", false));
            try
            {
                auto provider = service->castedInstance<PocoDDS::Protocols::ProtocolService>();
                const auto details = provider->diagnostics();
                item->set("name", provider->name());
                item->set("open", provider->isOpen());
                item->set("desiredOpen", provider->desiredOpen());
                item->set("diagnostics", protocolDiagnosticsJson(details, provider->failure()));
                const auto failure = provider->failure();
                if (!failure.code.empty() || !details.lastError.empty())
                {
                    diagnosticEvents().observe(_context->logger(), "protocol",
                        properties.get("pdr.protocol.id", service->name()), failure);
                    PocoDDS::Observability::Metrics::global().addCounter(
                        "pdr.diagnostics.failure.samples", 1,
                        {{"domain", "protocol"},
                         {"instance", properties.get("pdr.protocol.id", service->name())},
                         {"code", failure.code.empty()
                            ? "PDR-PROTOCOL-UNCLASSIFIED" : failure.code},
                         {"category", PocoDDS::Reliability::toString(failure.kind)},
                         {"active", (failure.code.empty() ? !details.lastError.empty()
                                                          : failure.active) ? "true" : "false"}},
                        "Observed structured diagnostic failures", "{sample}");
                }
            }
            catch (const std::exception& error)
            {
                item->set("open", false);
                item->set("error", error.what());
            }
            protocols->add(item);
        }
        Poco::JSON::Object root;
        root.set("schemaVersion", 1);
        root.set("count", protocols->size());
        root.set("protocols", protocols);
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }

private:
    void handleLifecycle(Poco::Net::HTTPServerRequest& request,
                         Poco::Net::HTTPServerResponse& response,
                         const std::string& principal)
    {
        ManagementAuditScope audit(request, response, principal, "protocol-lifecycle");
        audit.describe("", "", request.get("X-PDR-Request-Id", ""));
        try
        {
            Poco::JSON::Parser parser;
            auto body = parser.parse(request.stream()).extract<Poco::JSON::Object::Ptr>();
            const std::string id = body->getValue<std::string>("id");
            const std::string action = body->getValue<std::string>("action");
            audit.describe(id, action, request.get("X-PDR-Request-Id", ""));
            std::ostringstream fingerprint;
            body->stringify(fingerprint);
            auto requestGuard = beginManagementRequest(
                request, response, "/api/v1/protocols|" + fingerprint.str());
            if (!requestGuard.proceed()) return;
            Poco::OSP::ServiceRef::Ptr selected;
            for (const auto& service : _context->registry().find("pdr.protocol"))
            {
                if (service->properties().get("pdr.protocol.id", service->name()) == id)
                {
                    selected = service;
                    break;
                }
            }
            if (!selected)
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                                     "protocol instance not found");
            auto execute = [selected, id, action](const ManagementTaskContext* taskContext = nullptr,
                                                  int stabilityWindowMilliseconds = 0) {
                if (taskContext) taskContext->checkpoint();
                auto provider = selected->castedInstance<PocoDDS::Protocols::ProtocolService>();
                if (action == "open") provider->open();
                else if (action == "close") provider->close();
                else if (action == "restart") provider->restart();
                else
                    throw Poco::InvalidArgumentException(
                        "unsupported protocol lifecycle action");
                if (taskContext) taskContext->checkpoint();
                if (stabilityWindowMilliseconds > 0)
                {
                    const bool expectedOpen = action != "close";
                    auto stableSince = std::chrono::steady_clock::now();
                    while (std::chrono::duration_cast<std::chrono::milliseconds>(
                               std::chrono::steady_clock::now() - stableSince).count() <
                           stabilityWindowMilliseconds)
                    {
                        if (taskContext) taskContext->checkpoint();
                        if (provider->isOpen() != expectedOpen)
                            stableSince = std::chrono::steady_clock::now();
                        std::this_thread::sleep_for(std::chrono::milliseconds(25));
                    }
                }
                Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
                result->set("id", id);
                result->set("action", action);
                result->set("open", provider->isOpen());
                const auto details = provider->diagnostics();
                result->set("diagnostics", protocolDiagnosticsJson(details, provider->failure()));
                return result;
            };
            if (body->optValue<bool>("async", false))
            {
                if (!managementTaskSubmissionAvailable(response)) return;
                const int timeout = body->optValue<int>("startTimeoutMilliseconds", 30000);
                const int notBefore = body->optValue<int>("notBeforeMilliseconds", 0);
                const int executionTimeout = body->optValue<int>(
                    "executionTimeoutMilliseconds", 30000);
                const int stabilityWindow = body->optValue<int>(
                    "stabilityWindowMilliseconds", 0);
                if (timeout < 1 || timeout > 3600000)
                    throw Poco::InvalidArgumentException(
                        "startTimeoutMilliseconds must be between 1 and 3600000");
                if (notBefore < 0 || notBefore >= timeout)
                    throw Poco::InvalidArgumentException(
                        "notBeforeMilliseconds must be non-negative and less than the start timeout");
                if (executionTimeout < 1 || executionTimeout > 3600000)
                    throw Poco::InvalidArgumentException(
                        "executionTimeoutMilliseconds must be between 1 and 3600000");
                if (stabilityWindow < 0 || stabilityWindow > 300000 ||
                    stabilityWindow >= executionTimeout)
                    throw Poco::InvalidArgumentException(
                        "stabilityWindowMilliseconds must be non-negative, at most 300000, "
                        "and less than the execution timeout");
                auto task = managementTaskManager().submit(
                    "protocol-lifecycle", id, action, principal, requestGuard.requestId(),
                    timeout, notBefore, executionTimeout,
                    [execute, stabilityWindow](const ManagementTaskContext& context) {
                        return execute(&context, stabilityWindow);
                    });
                Poco::JSON::Object accepted;
                accepted.set("message", "protocol lifecycle task accepted");
                accepted.set("task", task);
                accepted.set("requestId", requestGuard.requestId());
                accepted.set("idempotentReplay", false);
                requestGuard.complete("protocol-lifecycle", id, action);
                audit.succeeded();
                response.setStatus(Poco::Net::HTTPResponse::HTTP_ACCEPTED);
                response.setContentType("application/json; charset=utf-8");
                accepted.stringify(response.send());
                return;
            }
            auto operationResult = execute(nullptr, 0);
            Poco::JSON::Object result;
            result.set("message", "protocol lifecycle operation completed");
            for (const auto& name : operationResult->getNames())
                result.set(name, operationResult->get(name));
            result.set("requestId", requestGuard.requestId());
            result.set("idempotentReplay", false);
            requestGuard.complete("protocol-lifecycle", id, action);
            audit.succeeded();
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentType("application/json; charset=utf-8");
            response.set("Cache-Control", "no-store");
            result.stringify(response.send());
        }
        catch (const std::exception& error)
        {
            audit.error(error.what());
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST, error.what());
        }
    }

    Poco::OSP::BundleContext::Ptr _context;
};

class ProcessLogsHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Poco::URI uri(request.getURI());
        std::string processId;
        std::string processName;
        int limit = 500;
        for (const auto& parameter : uri.getQueryParameters())
        {
            if (parameter.first == "id") processId = parameter.second;
            else if (parameter.first == "name") processName = parameter.second;
            else if (parameter.first == "limit")
            {
                try { limit = Poco::NumberParser::parse(parameter.second); }
                catch (...) {}
            }
        }
        limit = std::max(20, std::min(limit, 1000));

        std::string logName = "pdr-runtime";
        if (!processId.empty() &&
            processId != std::to_string(Poco::Process::id()))
        {
            logName.clear();
            for (const char character : processName)
            {
                const unsigned char value = static_cast<unsigned char>(character);
                if (std::isalnum(value) || character == '.' || character == '_' ||
                    character == '-')
                    logName += character;
            }
            const auto executableSuffix = logName.rfind(".exe");
            if (executableSuffix != std::string::npos &&
                executableSuffix + 4 == logName.size())
                logName.resize(executableSuffix);
        }

        std::deque<std::string> lines;
        if (!logName.empty())
        {
            Poco::Path path("logs");
            path.append(logName + ".log");
            path.makeAbsolute();
            std::ifstream input(path.toString());
            std::string line;
            while (std::getline(input, line))
            {
                lines.push_back(line);
                if (lines.size() > static_cast<std::size_t>(limit))
                    lines.pop_front();
            }
        }

        Poco::JSON::Array::Ptr jsonLines = new Poco::JSON::Array;
        for (const auto& line : lines)
            jsonLines->add(line);
        Poco::JSON::Object root;
        root.set("processId", processId);
        root.set("lines", jsonLines);
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json");
        root.stringify(response.send());
    }
};

class ProcessDetailHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit ProcessDetailHandler(Poco::OSP::BundleContext::Ptr context)
        : _context(context)
    {
    }

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Poco::URI uri(request.getURI());
        std::string processId;
        std::string processName;
        for (const auto& parameter : uri.getQueryParameters())
        {
            if (parameter.first == "id") processId = parameter.second;
            else if (parameter.first == "name") processName = parameter.second;
        }
        const std::string mainId = std::to_string(Poco::Process::id());
        const bool mainProcess = processId.empty() || processId == mainId;
        if (mainProcess)
        {
            processId = mainId;
            processName = "pdr-runtime";
        }
        std::string processState = "running";
        std::string processLocation = "local";
        if (!mainProcess)
        {
            if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
            {
                for (const auto& info : manager->processes())
                {
                    if (info.name == processName)
                    {
                        processId = std::to_string(info.processId);
                        processState = info.state;
                        processLocation = info.location;
                        break;
                    }
                }
            }
        }

        Poco::JSON::Object root;
        Poco::JSON::Object::Ptr process = new Poco::JSON::Object;
        process->set("id", processId);
        process->set("pid", processId);
        process->set("name", processName);
        process->set("main", mainProcess);
        process->set("state", processState);
        process->set("location", processLocation);
        root.set("process", process);

        Poco::JSON::Array::Ptr children = new Poco::JSON::Array;
        if (mainProcess)
            appendChildren(children);
        else if (auto status = readChildStatus(processName))
        {
            if (status->has("children"))
                children = status->getArray("children");
        }
        root.set("children", children);

        Poco::JSON::Array::Ptr bundles = new Poco::JSON::Array;
        if (mainProcess)
        {
            std::vector<Poco::OSP::Bundle::Ptr> loadedBundles;
            _context->listBundles(loadedBundles);
            for (const auto& loadedBundle : loadedBundles)
            {
                Poco::JSON::Object::Ptr bundle = new Poco::JSON::Object;
                bundle->set("id", loadedBundle->symbolicName());
                bundle->set("name", loadedBundle->name());
                bundle->set("version", loadedBundle->version().toString());
                bundle->set("state", loadedBundle->stateString());
                bundle->set("manageable", manageableBundle(loadedBundle->symbolicName()));
                appendBundleGovernance(_context, loadedBundle, bundle);
                bundles->add(bundle);
            }
        }
        else
        {
            if (auto status = readChildStatus(processName))
            {
                if (status->has("bundles"))
                    bundles = status->getArray("bundles");
            }
            if (bundles->size() == 0)
                appendRepositoryBundles(processName, bundles);
        }
        root.set("bundles", bundles);

        Poco::JSON::Object::Ptr resources = new Poco::JSON::Object;
        appendResources(processId, mainProcess, resources);
        root.set("resources", resources);

        Poco::JSON::Object::Ptr configuration = new Poco::JSON::Object;
        appendConfiguration(processName, mainProcess, configuration);
        root.set("configuration", configuration);
        Poco::JSON::Array::Ptr editable = new Poco::JSON::Array;
        if (mainProcess)
        {
            for (const auto& item : *configuration)
                if (editableConfiguration(item.first)) editable->add(item.first);
        }
        root.set("editableConfiguration", editable);

        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json");
        root.stringify(response.send());
    }

private:
    static Poco::JSON::Object::Ptr readChildStatus(const std::string& processName)
    {
        Poco::Path path("processes");
        path.append(safeName(processName));
        path.append("pdr-process-status.json");
        path.makeAbsolute();
        if (!Poco::File(path).exists())
            return {};
        try
        {
            std::ifstream input(path.toString());
            Poco::JSON::Parser parser;
            return parser.parse(input).extract<Poco::JSON::Object::Ptr>();
        }
        catch (...)
        {
            return {};
        }
    }

    static std::string safeName(const std::string& name)
    {
        std::string result;
        for (const char character : name)
        {
            const unsigned char value = static_cast<unsigned char>(character);
            if (std::isalnum(value) || character == '.' || character == '_' ||
                character == '-')
                result += character;
        }
        if (result.size() > 4 && result.substr(result.size() - 4) == ".exe")
            result.resize(result.size() - 4);
        return result;
    }

    static void appendChildren(Poco::JSON::Array::Ptr children)
    {
        if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
        {
            for (const auto& info : manager->processes())
            {
                Poco::JSON::Object::Ptr child = new Poco::JSON::Object;
                child->set("id", info.name);
                child->set("pid", info.processId);
                child->set("name", info.name);
                child->set("state", info.state);
                child->set("location", info.location);
                child->set("online", info.state == "running");
                child->set("host", info.location == "local" ?
                                       Poco::Environment::nodeName() : "远程主机");
                child->set("manageable", info.manageable);
                child->set("required", info.required);
                children->add(child);
            }
            return;
        }
#if defined(POCO_OS_FAMILY_WINDOWS)
        HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if (snapshot == INVALID_HANDLE_VALUE)
            return;
        PROCESSENTRY32W entry{};
        entry.dwSize = sizeof(entry);
        if (Process32FirstW(snapshot, &entry))
        {
            do
            {
                if (entry.th32ParentProcessID != GetCurrentProcessId() ||
                    _wcsicmp(entry.szExeFile, L"conhost.exe") == 0)
                    continue;
                std::string name;
                Poco::UnicodeConverter::toUTF8(entry.szExeFile, name);
                Poco::JSON::Object::Ptr child = new Poco::JSON::Object;
                child->set("id", std::to_string(entry.th32ProcessID));
                child->set("pid", entry.th32ProcessID);
                child->set("name", name);
                child->set("state", "running");
                child->set("location", "local");
                child->set("online", true);
                child->set("host", Poco::Environment::nodeName());
                child->set("manageable", false);
                children->add(child);
            }
            while (Process32NextW(snapshot, &entry));
        }
        CloseHandle(snapshot);
#endif
    }

    static void appendRepositoryBundles(const std::string& processName,
                                        Poco::JSON::Array::Ptr bundles)
    {
        Poco::Path path("processes");
        path.append(safeName(processName));
        path.append("bundles");
        path.makeAbsolute();
        Poco::File directory(path);
        if (!directory.exists() || !directory.isDirectory())
            return;
        for (Poco::DirectoryIterator iterator(path); iterator != Poco::DirectoryIterator();
             ++iterator)
        {
            if (!iterator->isFile() || Poco::Path(iterator.path()).getExtension() != "bndl")
                continue;
            const std::string baseName = Poco::Path(iterator.path()).getBaseName();
            const auto separator = baseName.rfind('_');
            Poco::JSON::Object::Ptr bundle = new Poco::JSON::Object;
            bundle->set("id", separator == std::string::npos ?
                                    baseName : baseName.substr(0, separator));
            bundle->set("name", separator == std::string::npos ?
                                      baseName : baseName.substr(0, separator));
            bundle->set("version", separator == std::string::npos ?
                                         "" : baseName.substr(separator + 1));
            bundle->set("state", "installed");
            bundles->add(bundle);
        }
    }

    void appendResources(const std::string& processId, bool mainProcess,
                         Poco::JSON::Object::Ptr resources)
    {
        if (mainProcess)
        {
            const auto serviceRef = _context->registry().findByName(SERVICE_NAME);
            if (serviceRef)
            {
                const auto history =
                    serviceRef->castedInstance<SystemMonitoringService>()->history();
                if (!history.empty())
                {
                    const auto& sample = history.back();
                    resources->set("cpuPercent", sample.cpuPercent);
                    resources->set("memoryPercent", sample.memoryPercent);
                    resources->set("memoryUsedMb", sample.memoryUsedMb);
                    resources->set("memoryTotalMb", sample.memoryTotalMb);
                    resources->set("networkReceiveKbps", sample.networkReceiveKbps);
                    resources->set("networkSendKbps", sample.networkSendKbps);
                    resources->set("threadCount", sample.threadCount);
                    resources->set("diskPercent", sample.diskPercent);
                }
            }
            return;
        }

#if defined(POCO_OS_FAMILY_WINDOWS)
        DWORD pid = 0;
        try { pid = static_cast<DWORD>(std::stoul(processId)); }
        catch (...) { return; }
        HANDLE processHandle =
            OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, FALSE, pid);
        if (processHandle)
        {
            PROCESS_MEMORY_COUNTERS_EX counters{};
            if (GetProcessMemoryInfo(
                    processHandle, reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&counters),
                    sizeof(counters)))
            {
                resources->set("memoryUsedMb",
                               counters.WorkingSetSize / (1024ULL * 1024ULL));
                MEMORYSTATUSEX memory{};
                memory.dwLength = sizeof(memory);
                if (GlobalMemoryStatusEx(&memory) && memory.ullTotalPhys != 0)
                    resources->set(
                        "memoryPercent",
                        100.0 * static_cast<double>(counters.WorkingSetSize) /
                            static_cast<double>(memory.ullTotalPhys));
            }

            FILETIME creation;
            FILETIME exit;
            FILETIME kernel;
            FILETIME user;
            FILETIME now;
            GetSystemTimeAsFileTime(&now);
            if (GetProcessTimes(processHandle, &creation, &exit, &kernel, &user))
            {
                const auto ticks = [](const FILETIME& value) {
                    return (static_cast<unsigned long long>(value.dwHighDateTime) << 32) |
                        value.dwLowDateTime;
                };
                static Poco::FastMutex cpuMutex;
                static std::unordered_map<DWORD, std::pair<unsigned long long,
                                                           unsigned long long>> previous;
                Poco::FastMutex::ScopedLock lock(cpuMutex);
                const auto processTicks = ticks(kernel) + ticks(user);
                const auto wallTicks = ticks(now);
                const auto found = previous.find(pid);
                if (found != previous.end() && wallTicks > found->second.second)
                {
                    const double cores =
                        static_cast<double>(
                            std::max(1U, Poco::Environment::processorCount()));
                    resources->set(
                        "cpuPercent",
                        100.0 * static_cast<double>(processTicks - found->second.first) /
                            static_cast<double>(wallTicks - found->second.second) / cores);
                }
                previous[pid] = {processTicks, wallTicks};
            }
            CloseHandle(processHandle);
        }
        Poco::UInt64 threads = 0;
        HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        if (snapshot != INVALID_HANDLE_VALUE)
        {
            THREADENTRY32 entry{};
            entry.dwSize = sizeof(entry);
            if (Thread32First(snapshot, &entry))
            {
                do
                {
                    if (entry.th32OwnerProcessID == pid) ++threads;
                }
                while (Thread32Next(snapshot, &entry));
            }
            CloseHandle(snapshot);
        }
        resources->set("threadCount", threads);
#endif
        if (!resources->has("cpuPercent")) resources->set("cpuPercent", 0);
        resources->set("diskPercent", 0);
        resources->set("networkReceiveKbps", 0);
        resources->set("networkSendKbps", 0);
    }

    static bool sensitiveKey(const std::string& key)
    {
        std::string lower = key;
        std::transform(lower.begin(), lower.end(), lower.begin(),
                       [](unsigned char value) { return static_cast<char>(std::tolower(value)); });
        return lower.find("password") != std::string::npos ||
            lower.find("secret") != std::string::npos ||
            lower.find("token") != std::string::npos ||
            lower.find("privatekey") != std::string::npos;
    }

    static void appendConfiguration(const std::string& processName, bool mainProcess,
                                    Poco::JSON::Object::Ptr configuration)
    {
        Poco::Path path;
        if (mainProcess)
        {
            path = Poco::Path("pdr-runtime.properties").makeAbsolute();
        }
        else
        {
            path = Poco::Path("processes");
            path.append(safeName(processName));
            path.append(safeName(processName) + ".properties");
            path.makeAbsolute();
        }
        if (!Poco::File(path).exists())
            return;
        try
        {
            Poco::AutoPtr<Poco::Util::PropertyFileConfiguration> values =
                new Poco::Util::PropertyFileConfiguration(path.toString());
            std::function<void(const std::string&)> appendKeys;
            appendKeys = [&](const std::string& prefix) {
                Poco::Util::AbstractConfiguration::Keys keys;
                values->keys(prefix, keys);
                for (const auto& key : keys)
                {
                    const std::string fullKey = prefix.empty() ? key : prefix + "." + key;
                    Poco::Util::AbstractConfiguration::Keys children;
                    values->keys(fullKey, children);
                    if (!children.empty())
                        appendKeys(fullKey);
                    else
                        configuration->set(
                            fullKey, sensitiveKey(fullKey) ?
                                         "••••••••" : values->getRawString(fullKey, ""));
                }
            };
            appendKeys("");
        }
        catch (...) {}
    }

    Poco::OSP::BundleContext::Ptr _context;
};

class ProcessLifecycleHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        std::string principal;
        if (!managementAuthorized(request, response, "process.manage", &principal,
                                  "process-lifecycle")) return;
        ManagementAuditScope audit(request, response, principal, "process-lifecycle");
        audit.describe("", "", request.get("X-PDR-Request-Id", ""));
        try
        {
            Poco::JSON::Parser parser;
            auto body = parser.parse(request.stream()).extract<Poco::JSON::Object::Ptr>();
            const std::string id = body->getValue<std::string>("id");
            const std::string action = body->getValue<std::string>("action");
            audit.describe(id, action, request.get("X-PDR-Request-Id", ""));
            std::ostringstream fingerprint;
            body->stringify(fingerprint);
            auto requestGuard = beginManagementRequest(
                request, response, "/api/v1/process-lifecycle|" + fingerprint.str());
            if (!requestGuard.proceed()) return;
            auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active();
            if (!manager)
                return sendJsonError(response,
                                     Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                                     "子进程管理器尚未就绪。");

            auto execute = [manager, id, action](const ManagementTaskContext* taskContext = nullptr) {
                if (taskContext) taskContext->checkpoint();
                bool completed = false;
                if (action == "start") completed = manager->start(id);
                else if (action == "stop") completed = manager->stop(id);
                else if (action == "restart") completed = manager->restart(id);
                else throw Poco::InvalidArgumentException("不支持的进程生命周期操作。");
                if (!completed)
                    throw Poco::InvalidAccessException(
                        "远程进程或未知进程不能由本机直接操作。");
                if (taskContext) taskContext->checkpoint();
                Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
                result->set("id", id);
                result->set("action", action);
                return result;
            };
            if (body->optValue<bool>("async", false))
            {
                if (!managementTaskSubmissionAvailable(response)) return;
                const int timeout = body->optValue<int>("startTimeoutMilliseconds", 30000);
                const int notBefore = body->optValue<int>("notBeforeMilliseconds", 0);
                const int executionTimeout = body->optValue<int>(
                    "executionTimeoutMilliseconds", 30000);
                if (timeout < 1 || timeout > 3600000)
                    throw Poco::InvalidArgumentException(
                        "startTimeoutMilliseconds must be between 1 and 3600000");
                if (notBefore < 0 || notBefore >= timeout)
                    throw Poco::InvalidArgumentException(
                        "notBeforeMilliseconds must be non-negative and less than the start timeout");
                if (executionTimeout < 1 || executionTimeout > 3600000)
                    throw Poco::InvalidArgumentException(
                        "executionTimeoutMilliseconds must be between 1 and 3600000");
                auto task = managementTaskManager().submit(
                    "process-lifecycle", id, action, principal, requestGuard.requestId(),
                    timeout, notBefore, executionTimeout,
                    [execute](const ManagementTaskContext& context) { return execute(&context); });
                Poco::JSON::Object accepted;
                accepted.set("message", "子进程任务已进入队列");
                accepted.set("task", task);
                accepted.set("requestId", requestGuard.requestId());
                accepted.set("idempotentReplay", false);
                requestGuard.complete("process-lifecycle", id, action);
                audit.succeeded();
                response.setStatus(Poco::Net::HTTPResponse::HTTP_ACCEPTED);
                response.setContentType("application/json");
                accepted.stringify(response.send());
                return;
            }
            try { execute(nullptr); }
            catch (const Poco::InvalidAccessException& exception)
            {
                audit.error(exception.displayText());
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                                     exception.displayText());
            }

            Poco::JSON::Object result;
            result.set("message", "子进程操作已完成");
            result.set("id", id);
            result.set("action", action);
            result.set("requestId", requestGuard.requestId());
            result.set("idempotentReplay", false);
            requestGuard.complete("process-lifecycle", id, action);
            audit.succeeded();
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentType("application/json");
            result.stringify(response.send());
        }
        catch (const std::exception& exception)
        {
            audit.error(exception.what());
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST, exception.what());
        }
    }
};

class BundleLifecycleHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit BundleLifecycleHandler(Poco::OSP::BundleContext::Ptr context): _context(context) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        std::string principal;
        if (!managementAuthorized(request, response, "bundle.manage", &principal,
                                  "bundle-lifecycle")) return;
        ManagementAuditScope audit(request, response, principal, "bundle-lifecycle");
        audit.describe("", "", request.get("X-PDR-Request-Id", ""));
        try
        {
            Poco::JSON::Parser parser;
            auto body = parser.parse(request.stream()).extract<Poco::JSON::Object::Ptr>();
            const std::string id = body->getValue<std::string>("id");
            const std::string action = body->getValue<std::string>("action");
            audit.describe(id, action, request.get("X-PDR-Request-Id", ""));
            std::ostringstream fingerprint;
            body->stringify(fingerprint);
            auto requestGuard = beginManagementRequest(
                request, response, "/api/v1/bundle-lifecycle|" + fingerprint.str());
            if (!requestGuard.proceed()) return;
            if (!manageableBundle(id))
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                                     "该 Bundle 属于核心基础设施，禁止在线操作。");
            Poco::OSP::Bundle::Ptr bundle = _context->findBundle(id);
            if (!bundle)
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                                     "未找到 Bundle。");
            if (action == "reset-quarantine")
            {
                pluginQuarantineManager().reset(
                    bundle, body->optValue<bool>("confirmPersistenceRecovery", false));
                Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
                result->set("message", "插件隔离状态已重置；请显式启动并观察稳定性。");
                result->set("id", id);
                result->set("action", action);
                result->set("requestId", requestGuard.requestId());
                result->set("idempotentReplay", false);
                appendPluginQuarantineGovernance(id, result);
                requestGuard.complete("bundle-lifecycle", id, action);
                audit.succeeded();
                response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
                response.setContentType("application/json");
                result->stringify(response.send());
                return;
            }
            if ((action == "start" || action == "restart") &&
                pluginQuarantineManager().blocked(id))
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_CONFLICT,
                    "插件已被隔离；检查 quarantineLastError 后执行 reset-quarantine。");
            Poco::JSON::Object::Ptr governance = new Poco::JSON::Object;
            if (!appendBundleGovernance(_context, bundle, governance))
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_CONFLICT,
                    "Bundle 依赖兼容性预检失败；请先检查进程详情中的 dependencies。");
            auto execute = [bundle, id, action](const ManagementTaskContext* taskContext = nullptr) mutable {
                if (taskContext) taskContext->checkpoint();
                if (action == "start")
                {
                    if (bundle->state() == Poco::OSP::Bundle::BUNDLE_INSTALLED) bundle->resolve();
                    if (bundle->state() == Poco::OSP::Bundle::BUNDLE_RESOLVED) bundle->start();
                }
                else if (action == "stop")
                {
                    if (bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE) bundle->stop();
                }
                else if (action == "restart")
                {
                    if (bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE) bundle->stop();
                    if (bundle->state() == Poco::OSP::Bundle::BUNDLE_INSTALLED) bundle->resolve();
                    if (bundle->state() == Poco::OSP::Bundle::BUNDLE_RESOLVED) bundle->start();
                }
                else throw Poco::InvalidArgumentException("不支持的生命周期操作。");
                if (taskContext) taskContext->checkpoint();
                Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
                result->set("id", id);
                result->set("state", bundle->stateString());
                return result;
            };
            if (body->optValue<bool>("async", false))
            {
                if (!managementTaskSubmissionAvailable(response)) return;
                const int timeout = body->optValue<int>("startTimeoutMilliseconds", 30000);
                const int notBefore = body->optValue<int>("notBeforeMilliseconds", 0);
                const int executionTimeout = body->optValue<int>(
                    "executionTimeoutMilliseconds", 30000);
                if (timeout < 1 || timeout > 3600000)
                    throw Poco::InvalidArgumentException(
                        "startTimeoutMilliseconds must be between 1 and 3600000");
                if (notBefore < 0 || notBefore >= timeout)
                    throw Poco::InvalidArgumentException(
                        "notBeforeMilliseconds must be non-negative and less than the start timeout");
                if (executionTimeout < 1 || executionTimeout > 3600000)
                    throw Poco::InvalidArgumentException(
                        "executionTimeoutMilliseconds must be between 1 and 3600000");
                auto task = managementTaskManager().submit(
                    "bundle-lifecycle", id, action, principal, requestGuard.requestId(),
                    timeout, notBefore, executionTimeout,
                    [execute](const ManagementTaskContext& context) mutable {
                        return execute(&context);
                    });
                Poco::JSON::Object accepted;
                accepted.set("message", "Bundle 任务已进入队列");
                accepted.set("task", task);
                accepted.set("requestId", requestGuard.requestId());
                accepted.set("idempotentReplay", false);
                requestGuard.complete("bundle-lifecycle", id, action);
                audit.succeeded();
                response.setStatus(Poco::Net::HTTPResponse::HTTP_ACCEPTED);
                response.setContentType("application/json");
                accepted.stringify(response.send());
                return;
            }
            auto operationResult = execute(nullptr);

            Poco::JSON::Object result;
            result.set("message", "Bundle 操作已完成");
            for (const auto& name : operationResult->getNames())
                result.set(name, operationResult->get(name));
            result.set("requestId", requestGuard.requestId());
            result.set("idempotentReplay", false);
            requestGuard.complete("bundle-lifecycle", id, action);
            audit.succeeded();
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentType("application/json");
            result.stringify(response.send());
        }
        catch (const std::exception& exception)
        {
            audit.error(exception.what());
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST, exception.what());
        }
    }
private:
    Poco::OSP::BundleContext::Ptr _context;
};

class ProcessConfigHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit ProcessConfigHandler(Poco::OSP::BundleContext::Ptr context): _context(context) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        std::lock_guard<std::mutex> updateLock(configurationUpdateMutex());
        const std::string transactionId =
            std::to_string(Poco::Timestamp().epochMicroseconds());
        const Poco::Int64 timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
        std::string action = "apply";
        std::string key;
        std::string value;
        std::string oldValue;
        std::string owner;
        std::string managementPrincipal;
        Poco::Path path("pdr-runtime.properties");
        path.makeAbsolute();
        Poco::Path stagedPath;
        Poco::Path backupPath;
        Poco::Path metadataPath(path.toString() + ".rollback.meta.json");
        Poco::Path stagedMetadataPath(path.toString() + ".rollback.meta.json.new");
        Poco::Path previousMetadataPath(path.toString() + ".rollback.meta.json.previous");
        Poco::AutoPtr<Poco::OSP::PreferencesService> preferences;
        Poco::OSP::Bundle::Ptr ownerBundle;
        bool fileCommitted = false;
        bool metadataCommitted = false;
        bool runtimeApplied = false;
        bool ownerWasActive = false;
        bool conflict = false;
        auto failureStatus = Poco::Net::HTTPResponse::HTTP_BAD_REQUEST;
        ManagementRequestGuard requestGuard;
        std::unique_ptr<ManagementAuditScope> managementAudit;
        try
        {
            if (request.getMethod() == Poco::Net::HTTPRequest::HTTP_GET)
            {
                Poco::AutoPtr<Poco::Util::PropertyFileConfiguration> file =
                    new Poco::Util::PropertyFileConfiguration(path.toString());
                Poco::JSON::Object::Ptr configuration = new Poco::JSON::Object;
                Poco::JSON::Array::Ptr editable = new Poco::JSON::Array;
                std::function<void(const std::string&)> append;
                append = [&](const std::string& prefix) {
                    Poco::Util::AbstractConfiguration::Keys keys;
                    file->keys(prefix, keys);
                    for (const auto& child : keys)
                    {
                        const std::string fullKey = prefix.empty() ? child : prefix + "." + child;
                        Poco::Util::AbstractConfiguration::Keys descendants;
                        file->keys(fullKey, descendants);
                        if (!descendants.empty()) append(fullKey);
                        else if (editableConfiguration(fullKey))
                        {
                            configuration->set(fullKey, file->getRawString(fullKey, ""));
                            editable->add(fullKey);
                        }
                    }
                };
                append("");
                Poco::JSON::Object result;
                result.set("schemaVersion", 1);
                result.set("managementAuthenticationRequired",
                           managementAuthorization().required);
                Poco::JSON::Object::Ptr managementSession = new Poco::JSON::Object;
                Poco::JSON::Array::Ptr permissions = new Poco::JSON::Array;
                if (!managementAuthorization().required)
                {
                    managementSession->set("authenticated", true);
                    managementSession->set("principal", "development-anonymous");
                    const auto& allPermissions = PocoDDS::Security::managementPermissions();
                    std::vector<std::string> ordered(allPermissions.begin(), allPermissions.end());
                    std::sort(ordered.begin(), ordered.end());
                    for (const auto& permission : ordered) permissions->add(permission);
                }
                else if (const auto principal = managementPrincipalForRequest(request))
                {
                    managementSession->set("authenticated", true);
                    managementSession->set("principal", principal->id);
                    std::vector<std::string> ordered(principal->permissions.begin(),
                                                     principal->permissions.end());
                    std::sort(ordered.begin(), ordered.end());
                    for (const auto& permission : ordered) permissions->add(permission);
                }
                else
                {
                    managementSession->set("authenticated", false);
                    managementSession->set("principal", "");
                }
                managementSession->set("permissions", permissions);
                result.set("managementSession", managementSession);
                result.set("configuration", configuration);
                result.set("editable", editable);
                const auto metadata = readJsonObject(metadataPath);
                const bool rollbackAvailable = metadata &&
                    Poco::File(path.toString() + ".rollback").exists();
                result.set("rollbackFileAvailable", rollbackAvailable);
                if (rollbackAvailable)
                {
                    Poco::JSON::Object::Ptr rollback = new Poco::JSON::Object;
                    rollback->set("transactionId", metadata->getValue<std::string>("transactionId"));
                    rollback->set("key", metadata->getValue<std::string>("key"));
                    rollback->set("action", metadata->getValue<std::string>("action"));
                    rollback->set("timestampMicroseconds",
                                  metadata->getValue<Poco::Int64>("timestampMicroseconds"));
                    result.set("rollback", rollback);
                }
                result.set("transactions", recentConfigurationAudit(path, 20));
                response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
                response.setContentType("application/json");
                result.stringify(response.send());
                return;
            }
            if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_POST)
                return sendJsonError(response,
                                     Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                                     "仅支持 GET 和 POST。");
            if (!managementAuthorized(request, response, "configuration.manage",
                                      &managementPrincipal, "configuration")) return;
            managementAudit = std::make_unique<ManagementAuditScope>(
                request, response, managementPrincipal, "configuration");
            managementAudit->describe("", action, request.get("X-PDR-Request-Id", ""));
            Poco::JSON::Parser parser;
            auto body = parser.parse(request.stream()).extract<Poco::JSON::Object::Ptr>();
            std::ostringstream fingerprint;
            body->stringify(fingerprint);
            requestGuard = beginManagementRequest(
                request, response, "/api/v1/process-config|" + fingerprint.str());
            if (!requestGuard.proceed()) return;
            if (body->has("action")) action = body->getValue<std::string>("action");
            if (action != "apply" && action != "rollback")
                throw Poco::InvalidArgumentException("action must be apply or rollback");

            Poco::AutoPtr<Poco::Util::PropertyFileConfiguration> file =
                new Poco::Util::PropertyFileConfiguration(path.toString());
            if (action == "rollback")
            {
                const auto metadata = readJsonObject(metadataPath);
                if (!metadata || !Poco::File(path.toString() + ".rollback").exists())
                {
                    conflict = true;
                    throw Poco::InvalidArgumentException("没有可回退的配置事务");
                }
                const std::string requestedId =
                    body->getValue<std::string>("transactionId");
                if (requestedId != metadata->getValue<std::string>("transactionId"))
                {
                    conflict = true;
                    throw Poco::InvalidArgumentException("回退事务已过期，请刷新后重试");
                }
                key = metadata->getValue<std::string>("key");
                value = metadata->getValue<std::string>("previousValue");
                if (!file->hasProperty(key) ||
                    file->getRawString(key) != metadata->getValue<std::string>("currentValue"))
                {
                    conflict = true;
                    throw Poco::InvalidArgumentException("当前配置已被外部修改，拒绝覆盖");
                }
            }
            else
            {
                key = body->getValue<std::string>("key");
                value = body->getValue<std::string>("value");
            }
            managementAudit->describe(key, action, requestGuard.requestId());
            if (!editableConfiguration(key))
            {
                failureStatus = Poco::Net::HTTPResponse::HTTP_FORBIDDEN;
                throw Poco::InvalidAccessException("该配置项为只读", key);
            }

            if (!file->hasProperty(key))
            {
                failureStatus = Poco::Net::HTTPResponse::HTTP_NOT_FOUND;
                throw Poco::NotFoundException("配置项不存在", key);
            }
            oldValue = file->getRawString(key);
            const auto preferencesRef =
                _context->registry().findByName(Poco::OSP::PreferencesService::SERVICE_NAME);
            if (!preferencesRef)
                throw Poco::NullPointerException("全局配置服务不可用");
            preferences = preferencesRef->castedInstance<Poco::OSP::PreferencesService>();

            Poco::AutoPtr<Poco::Util::MapConfiguration> candidate =
                new Poco::Util::MapConfiguration;
            copyConfiguration(*preferences->configuration(), *candidate);
            candidate->setString(key, value);
            PocoDDS::Configuration::ConfigurationValidator().validateOrThrow(*candidate);

            file->setString(key, value);
            stagedPath = Poco::Path(path.toString() + ".new");
            backupPath = Poco::Path(path.toString() + ".rollback");
            if (Poco::File(stagedPath).exists()) Poco::File(stagedPath).remove();
            file->save(stagedPath.toString());
            Poco::AutoPtr<Poco::Util::PropertyFileConfiguration> staged =
                new Poco::Util::PropertyFileConfiguration(stagedPath.toString());
            if (staged->getRawString(key) != value)
                throw Poco::DataException("暂存配置校验失败");

            Poco::JSON::Object metadata;
            metadata.set("transactionId", transactionId);
            metadata.set("action", action);
            metadata.set("key", key);
            metadata.set("previousValue", oldValue);
            metadata.set("currentValue", value);
            metadata.set("timestampMicroseconds", timestampMicroseconds);
            stageJsonObject(metadata, stagedMetadataPath);

            if (Poco::File(backupPath).exists()) Poco::File(backupPath).remove();
            Poco::File(path).copyTo(backupPath.toString());
            replaceConfigurationFile(stagedPath, path);
            fileCommitted = true;

            preferences->setConfiguration(key, value);
            runtimeApplied = true;
            if (key == "logging.loggers.root.level")
                Poco::Logger::root().setLevel(value);

            owner = configurationOwner(key);
            if (!owner.empty())
            {
                ownerBundle = _context->findBundle(owner);
                ownerWasActive = ownerBundle &&
                    ownerBundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE;
                if (ownerWasActive)
                {
                    if (!manageableBundle(owner))
                        throw Poco::InvalidAccessException("配置所属 Bundle 不允许在线重启", owner);
                    ownerBundle->stop();
                    ownerBundle->start();
                }
            }

            if (Poco::File(previousMetadataPath).exists())
                Poco::File(previousMetadataPath).remove();
            if (Poco::File(metadataPath).exists())
                Poco::File(metadataPath).copyTo(previousMetadataPath.toString());
            replaceConfigurationFile(stagedMetadataPath, metadataPath);
            metadataCommitted = true;

            Poco::JSON::Object audit;
            audit.set("transactionId", transactionId);
            audit.set("timestampMicroseconds", timestampMicroseconds);
            audit.set("action", action);
            audit.set("key", key);
            audit.set("status", "committed");
            audit.set("owner", owner);
            audit.set("ownerRestarted", ownerWasActive);
            audit.set("remoteAddress", request.clientAddress().toString());
            audit.set("requestId", requestGuard.requestId());
            audit.set("principal", managementPrincipal);
            appendConfigurationAudit(path, audit);
            if (Poco::File(previousMetadataPath).exists())
                Poco::File(previousMetadataPath).remove();

            Poco::JSON::Object result;
            result.set("message", action == "rollback" ? "配置已回退并生效" :
                (owner.empty() ? "配置已立即生效" : "配置已保存，相关 Bundle 已重启"));
            result.set("transactionId", transactionId);
            result.set("action", action);
            result.set("key", key);
            result.set("value", value);
            result.set("validated", true);
            result.set("persisted", true);
            result.set("applied", true);
            result.set("owner", owner);
            result.set("ownerRestarted", ownerWasActive);
            result.set("rolledBack", false);
            result.set("audited", true);
            result.set("requestId", requestGuard.requestId());
            result.set("idempotentReplay", false);
            result.set("principal", managementPrincipal);
            requestGuard.complete("configuration", key, action);
            managementAudit->succeeded();
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentType("application/json");
            result.stringify(response.send());
        }
        catch (const std::exception& exception)
        {
            bool rolledBack = false;
            try
            {
                if (metadataCommitted)
                {
                    if (Poco::File(previousMetadataPath).exists())
                    {
                        Poco::Path restoreMetadata(metadataPath.toString() + ".restore");
                        if (Poco::File(restoreMetadata).exists()) Poco::File(restoreMetadata).remove();
                        Poco::File(previousMetadataPath).copyTo(restoreMetadata.toString());
                        replaceConfigurationFile(restoreMetadata, metadataPath);
                    }
                    else if (Poco::File(metadataPath).exists()) Poco::File(metadataPath).remove();
                }
                if (fileCommitted && Poco::File(backupPath).exists())
                {
                    Poco::Path restorePath(path.toString() + ".restore");
                    if (Poco::File(restorePath).exists()) Poco::File(restorePath).remove();
                    Poco::File(backupPath).copyTo(restorePath.toString());
                    replaceConfigurationFile(restorePath, path);
                    rolledBack = true;
                }
                if (runtimeApplied && preferences)
                {
                    preferences->setConfiguration(key, oldValue);
                    if (key == "logging.loggers.root.level") Poco::Logger::root().setLevel(oldValue);
                }
                if (ownerWasActive && ownerBundle &&
                    ownerBundle->state() != Poco::OSP::Bundle::BUNDLE_ACTIVE)
                    ownerBundle->start();
            }
            catch (...) {}
            if (!stagedPath.toString().empty() && Poco::File(stagedPath).exists())
                try { Poco::File(stagedPath).remove(); } catch (...) {}
            if (Poco::File(stagedMetadataPath).exists())
                try { Poco::File(stagedMetadataPath).remove(); } catch (...) {}
            Poco::JSON::Object result;
            const auto* pocoException = dynamic_cast<const Poco::Exception*>(&exception);
            const std::string error =
                pocoException ? pocoException->displayText() : exception.what();
            if (managementAudit) managementAudit->error(error);
            try
            {
                Poco::JSON::Object audit;
                audit.set("transactionId", transactionId);
                audit.set("timestampMicroseconds", timestampMicroseconds);
                audit.set("action", action);
                audit.set("key", key);
                audit.set("status", rolledBack ? "rolled-back" : "rejected");
                audit.set("rolledBack", rolledBack);
                audit.set("error", error);
                audit.set("remoteAddress", request.clientAddress().toString());
                audit.set("requestId", requestGuard.requestId());
                audit.set("principal", managementPrincipal);
                appendConfigurationAudit(path, audit);
            }
            catch (...) {}
            result.set("error", error);
            result.set("transactionId", transactionId);
            result.set("action", action);
            result.set("key", key);
            result.set("persisted", false);
            result.set("applied", false);
            result.set("rolledBack", rolledBack);
            response.setStatus((fileCommitted || conflict) ?
                Poco::Net::HTTPResponse::HTTP_CONFLICT : failureStatus);
            response.setContentType("application/json");
            result.stringify(response.send());
        }
    }
private:
    Poco::OSP::BundleContext::Ptr _context;
};

class ManagementAuditHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
            return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                                 "management audit endpoint only supports GET");
        if (!managementAuthorized(request, response, "audit.read", nullptr,
                                  "management-audit-read")) return;
        std::size_t limit = 100;
        std::string operation;
        std::string status;
        std::string principal;
        Poco::URI uri(request.getURI());
        for (const auto& parameter : uri.getQueryParameters())
        {
            if (parameter.first == "limit")
            {
                int parsed = 0;
                if (!Poco::NumberParser::tryParse(parameter.second, parsed) ||
                    parsed < 1 || parsed > 1000)
                    return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                                         "limit must be between 1 and 1000");
                limit = static_cast<std::size_t>(parsed);
            }
            else if (parameter.first == "operation") operation = parameter.second;
            else if (parameter.first == "status") status = parameter.second;
            else if (parameter.first == "principal") principal = parameter.second;
        }
        auto events = recentManagementAudit(limit, operation, status, principal);
        Poco::JSON::Object result;
        result.set("schemaVersion", 1);
        result.set("enabled", managementAuthorization().auditEnabled);
        result.set("count", events->size());
        result.set("events", events);
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        result.stringify(response.send());
    }
};

class IdentityHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit IdentityHandler(Poco::OSP::BundleContext::Ptr context):
        _context(std::move(context))
    {
    }

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        std::string principal;
        if (!managementAuthorized(request, response, "identity.manage", &principal,
                                  "identity-configuration")) return;
        if (request.getMethod() == Poco::Net::HTTPRequest::HTTP_GET)
            return sendSnapshot(response, managementAuthorization().identityService->snapshot());
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_POST)
            return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                                 "identity endpoint supports GET and POST");

        auto requestGuard = beginManagementRequest(
            request, response, "/api/v1/identity|POST|reload");
        if (!requestGuard.proceed()) return;
        const auto started = Poco::Timestamp().epochMicroseconds();
        const auto before = managementAuthorization().identityService->snapshot();
        try
        {
            auto preferences = Poco::OSP::ServiceFinder::find<
                Poco::OSP::PreferencesService>(_context);
            const auto after = managementAuthorization().identityService->reload(
                *preferences->configuration());
            requestGuard.complete("identity-configuration", "management-principals", "reload");
            recordManagementAudit(request, principal, requestGuard.requestId(),
                                  "identity-configuration", "management-principals", "reload",
                                  "succeeded", 200, started);
            Poco::JSON::Object result;
            result.set("schemaVersion", 1);
            result.set("generationBefore", static_cast<Poco::UInt64>(before.generation));
            result.set("generation", static_cast<Poco::UInt64>(after.generation));
            result.set("required", after.required);
            result.set("principalCount", static_cast<Poco::UInt64>(after.principalCount));
            result.set("fileBackedPrincipalCount",
                       static_cast<Poco::UInt64>(after.fileBackedPrincipalCount));
            result.set("environmentBackedPrincipalCount",
                       static_cast<Poco::UInt64>(after.environmentBackedPrincipalCount));
            result.set("insecureFileCount",
                       static_cast<Poco::UInt64>(after.insecureFileCount));
            result.set("filePermissionChecksComplete", after.filePermissionChecksComplete);
            result.set("reloaded", true);
            result.set("requestId", requestGuard.requestId());
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentType("application/json; charset=utf-8");
            response.set("Cache-Control", "no-store");
            result.stringify(response.send());
        }
        catch (const std::exception& exception)
        {
            const auto current = managementAuthorization().identityService->snapshot();
            recordManagementAudit(request, principal, requestGuard.requestId(),
                                  "identity-configuration", "management-principals", "reload",
                                  "failed", 400, started, exception.what());
            Poco::JSON::Object result;
            result.set("error", "身份配置重载失败；旧身份快照仍然有效。");
            result.set("generation", static_cast<Poco::UInt64>(current.generation));
            result.set("unchanged", current.generation == before.generation);
            response.setStatus(Poco::Net::HTTPResponse::HTTP_BAD_REQUEST);
            response.setContentType("application/json; charset=utf-8");
            response.set("Cache-Control", "no-store");
            result.stringify(response.send());
        }
    }

private:
    static void sendSnapshot(Poco::Net::HTTPServerResponse& response,
                             const PocoDDS::Security::PrincipalStoreSnapshot& snapshot)
    {
        Poco::JSON::Object result;
        result.set("schemaVersion", 1);
        result.set("generation", static_cast<Poco::UInt64>(snapshot.generation));
        result.set("required", snapshot.required);
        result.set("principalCount", static_cast<Poco::UInt64>(snapshot.principalCount));
        result.set("fileBackedPrincipalCount",
                   static_cast<Poco::UInt64>(snapshot.fileBackedPrincipalCount));
        result.set("environmentBackedPrincipalCount",
                   static_cast<Poco::UInt64>(snapshot.environmentBackedPrincipalCount));
        result.set("insecureFileCount", static_cast<Poco::UInt64>(snapshot.insecureFileCount));
        result.set("filePermissionChecksComplete", snapshot.filePermissionChecksComplete);
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        result.stringify(response.send());
    }

    Poco::OSP::BundleContext::Ptr _context;
};

class ManagementTasksHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Poco::URI uri(request.getURI());
        constexpr const char* PREFIX = "/api/v1/management-tasks";
        std::string id = uri.getPath().substr(std::char_traits<char>::length(PREFIX));
        if (!id.empty() && id.front() == '/') id.erase(id.begin());
        if (request.getMethod() == Poco::Net::HTTPRequest::HTTP_GET)
            return handleGet(request, response, uri, id);
        if (request.getMethod() == Poco::Net::HTTPRequest::HTTP_DELETE && !id.empty())
            return handleCancel(request, response, id,
                                "/api/v1/management-tasks/" + id + "|DELETE");
        if (request.getMethod() == Poco::Net::HTTPRequest::HTTP_POST && id.empty())
        {
            try
            {
                auto body = Poco::JSON::Parser().parse(request.stream())
                    .extract<Poco::JSON::Object::Ptr>();
                if (body->getValue<std::string>("action") != "cancel")
                    throw Poco::InvalidArgumentException("unsupported task action");
                std::ostringstream fingerprint;
                body->stringify(fingerprint);
                return handleCancel(request, response, body->getValue<std::string>("id"),
                                    "/api/v1/management-tasks|" + fingerprint.str());
            }
            catch (const std::exception& exception)
            {
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                                     exception.what());
            }
        }
        sendJsonError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                      "management tasks support GET and item DELETE");
    }

private:
    void handleGet(Poco::Net::HTTPServerRequest& request,
                   Poco::Net::HTTPServerResponse& response,
                   const Poco::URI& uri, const std::string& id)
    {
        if (!managementAuthorized(request, response, "task.read", nullptr,
                                  "management-task-read")) return;
        if (!id.empty())
        {
            auto task = managementTaskManager().get(id);
            if (!task)
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                                     "management task not found");
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentType("application/json; charset=utf-8");
            response.set("Cache-Control", "no-store");
            task->stringify(response.send());
            return;
        }
        std::size_t limit = 100;
        std::string state;
        std::string operation;
        for (const auto& parameter : uri.getQueryParameters())
        {
            if (parameter.first == "limit")
            {
                int parsed = 0;
                if (!Poco::NumberParser::tryParse(parameter.second, parsed) ||
                    parsed < 1 || parsed > 1000)
                    return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                                         "limit must be between 1 and 1000");
                limit = static_cast<std::size_t>(parsed);
            }
            else if (parameter.first == "state") state = parameter.second;
            else if (parameter.first == "operation") operation = parameter.second;
        }
        auto tasks = managementTaskManager().list(limit, state, operation);
        Poco::JSON::Object result;
        result.set("schemaVersion", 1);
        result.set("count", tasks->size());
        result.set("tasks", tasks);
        result.set("persistence", managementTaskManager().persistenceStatus());
        result.set("idempotency", managementRequestLedgerStatus());
        result.set("scheduler", managementTaskManager().schedulerStatus());
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        result.stringify(response.send());
    }

    void handleCancel(Poco::Net::HTTPServerRequest& request,
                      Poco::Net::HTTPServerResponse& response,
                      const std::string& id, const std::string& fingerprint)
    {
        std::string principal;
        if (!managementAuthorized(request, response, "task.cancel", &principal,
                                  "management-task-cancel")) return;
        auto requestGuard = beginManagementRequest(
            request, response, fingerprint);
        if (!requestGuard.proceed()) return;
        ManagementAuditScope audit(request, response, principal, "management-task-cancel");
        audit.describe(id, "cancel", requestGuard.requestId());
        auto task = managementTaskManager().cancel(id);
        if (!task)
            return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                                 "management task not found");
        const std::string state = task->getValue<std::string>("state");
        const bool cancellationAccepted = state == "cancelled" ||
            (state == "running" && task->optValue<bool>("cancellationRequested", false));
        if (!cancellationAccepted)
        {
            audit.error("completed task cannot be cancelled");
            response.setStatus(Poco::Net::HTTPResponse::HTTP_CONFLICT);
        }
        else
        {
            requestGuard.complete("management-task-cancel", id, "cancel");
            audit.succeeded();
            response.setStatus(state == "cancelled"
                ? Poco::Net::HTTPResponse::HTTP_OK
                : Poco::Net::HTTPResponse::HTTP_ACCEPTED);
        }
        Poco::JSON::Object result;
        result.set("message", state == "cancelled" ? "management task cancelled" :
                   cancellationAccepted ? "management task cancellation requested" :
                   "completed task cannot be cancelled");
        result.set("task", task);
        result.set("requestId", requestGuard.requestId());
        result.set("idempotentReplay", false);
        response.setContentType("application/json; charset=utf-8");
        result.stringify(response.send());
    }
};

Poco::JSON::Object::Ptr traceFields(const PocoDDS::Observability::Fields& fields)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    for (const auto& field : fields) result->set(field.first, field.second);
    return result;
}

class HeartbeatBusinessHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Poco::URI uri(request.getURI());
        std::string traceId;
        for (const auto& parameter : uri.getQueryParameters())
            if (parameter.first == "traceId") traceId = parameter.second;
        Poco::JSON::Object root;
        if (traceId.empty())
        {
            Poco::JSON::Array::Ptr records = new Poco::JSON::Array;
            for (const auto& summary :
                 PocoDDS::Observability::globalTraceStore().recent(1000))
            {
                if (summary.businessName != "主子进程Fast-DDS心跳" &&
                    summary.businessName != "Qt3D多窗口协同业务")
                    continue;
                Poco::JSON::Object::Ptr record = new Poco::JSON::Object;
                record->set("traceId", summary.traceId);
                record->set("businessName", summary.businessName);
                record->set("businessInstanceId", summary.businessInstanceId);
                record->set("status", summary.status);
                record->set("startedUnixMicroseconds", summary.startedUnixMicroseconds);
                record->set("durationNanoseconds", summary.durationNanoseconds);
                record->set("stepCount", summary.stepCount);
                record->set("failedOperation", summary.failedOperation);
                records->add(record);
            }
            root.set("records", records);
        }
        else
        {
            Poco::JSON::Array::Ptr nodes = new Poco::JSON::Array;
            for (const auto& span :
                 PocoDDS::Observability::globalTraceStore().trace(traceId))
            {
                Poco::JSON::Object::Ptr node = new Poco::JSON::Object;
                node->set("operation", span.operation);
                node->set("serviceName", span.serviceName);
                node->set("bundleName", span.bundleName);
                node->set("hostName", span.hostName);
                node->set("processId", span.processId);
                node->set("traceId", span.traceId);
                node->set("spanId", span.spanId);
                node->set("parentSpanId", span.parentSpanId);
                node->set("status", span.status);
                node->set("errorCode", span.errorCode);
                node->set("errorMessage", span.errorMessage);
                node->set("startedUnixMicroseconds", span.startedUnixMicroseconds);
                node->set("endedUnixMicroseconds", span.endedUnixMicroseconds);
                node->set("durationNanoseconds", span.durationNanoseconds);
                node->set("inputs", traceFields(span.inputs));
                node->set("outputs", traceFields(span.outputs));
                nodes->add(node);
            }
            root.set("nodes", nodes);
        }
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }
};

class BusinessTracesHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        const std::string prefix = "/api/v1/business-traces/";
        const std::string path = Poco::URI(request.getURI()).getPath();
        Poco::JSON::Object root;
        if (path == "/api/v1/business-traces" ||
            path == "/api/v1/business-traces/")
        {
            Poco::JSON::Array::Ptr traces = new Poco::JSON::Array;
            for (const auto& summary :
                 PocoDDS::Observability::globalTraceStore().recent(1000))
            {
                Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
                item->set("traceId", summary.traceId);
                item->set("businessName", summary.businessName);
                item->set("businessInstanceId", summary.businessInstanceId);
                item->set("status", summary.status);
                item->set("startedUnixMicroseconds", summary.startedUnixMicroseconds);
                item->set("durationNanoseconds", summary.durationNanoseconds);
                item->set("stepCount", summary.stepCount);
                item->set("failedOperation", summary.failedOperation);
                traces->add(item);
            }
            root.set("traces", traces);
        }
        else if (path.rfind(prefix, 0) == 0)
        {
            std::string traceId;
            Poco::URI::decode(path.substr(prefix.size()), traceId);
            Poco::JSON::Array::Ptr nodes = new Poco::JSON::Array;
            for (const auto& span :
                 PocoDDS::Observability::globalTraceStore().trace(traceId))
            {
                Poco::JSON::Object::Ptr node = new Poco::JSON::Object;
                node->set("businessName", span.businessName);
                node->set("businessInstanceId", span.businessInstanceId);
                node->set("operation", span.operation);
                node->set("serviceName", span.serviceName);
                node->set("bundleName", span.bundleName);
                node->set("hostName", span.hostName);
                node->set("processId", span.processId);
                node->set("traceId", span.traceId);
                node->set("spanId", span.spanId);
                node->set("parentSpanId", span.parentSpanId);
                node->set("status", span.status);
                node->set("errorCode", span.errorCode);
                node->set("errorMessage", span.errorMessage);
                node->set("startedUnixMicroseconds", span.startedUnixMicroseconds);
                node->set("endedUnixMicroseconds", span.endedUnixMicroseconds);
                node->set("durationNanoseconds", span.durationNanoseconds);
                node->set("inputs", traceFields(span.inputs));
                node->set("outputs", traceFields(span.outputs));
                Poco::JSON::Array::Ptr logs = new Poco::JSON::Array;
                for (const auto& log : span.logs)
                {
                    Poco::JSON::Object::Ptr value = new Poco::JSON::Object;
                    value->set("timestampUnixMicroseconds",
                               log.timestampUnixMicroseconds);
                    value->set("level", log.level);
                    value->set("message", log.message);
                    value->set("fields", traceFields(log.fields));
                    logs->add(value);
                }
                node->set("logs", logs);
                nodes->add(node);
            }
            root.set("nodes", nodes);
        }
        else
        {
            return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                                 "未找到业务追踪。");
        }
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }
};

class BusinessTraceHistoryHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        try
        {
            PocoDDS::Observability::TraceHistoryQuery query;
            for (const auto& parameter : Poco::URI(request.getURI()).getQueryParameters())
            {
                if (parameter.first == "from" && !parameter.second.empty())
                    query.fromUnixMicroseconds =
                        Poco::NumberParser::parse64(parameter.second);
                else if (parameter.first == "to" && !parameter.second.empty())
                    query.toUnixMicroseconds =
                        Poco::NumberParser::parse64(parameter.second);
                else if (parameter.first == "name")
                    query.businessName = parameter.second;
                else if (parameter.first == "status")
                    query.status = parameter.second;
                else if (parameter.first == "limit" && !parameter.second.empty())
                    query.limit = static_cast<std::size_t>(
                        std::max(1, Poco::NumberParser::parse(parameter.second)));
                else if (parameter.first == "offset" && !parameter.second.empty())
                    query.offset = static_cast<std::size_t>(
                        std::max(0, Poco::NumberParser::parse(parameter.second)));
            }
            Poco::JSON::Array::Ptr records = new Poco::JSON::Array;
            const auto append = [](void* context, const char* traceId,
                                   const char* businessName,
                                   const char* businessInstanceId,
                                   const char* status,
                                   long long startedUnixMicroseconds,
                                   long long durationNanoseconds,
                                   std::size_t stepCount,
                                   const char* failedOperation) {
                auto* values = static_cast<Poco::JSON::Array*>(context);
                Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
                item->set("traceId", traceId);
                item->set("businessName", businessName);
                item->set("businessInstanceId", businessInstanceId);
                item->set("status", status);
                item->set("startedUnixMicroseconds", startedUnixMicroseconds);
                item->set("durationNanoseconds", durationNanoseconds);
                item->set("stepCount", stepCount);
                item->set("failedOperation", failedOperation);
                values->add(item);
            };
            const bool hasMore = PocoDDS::Observability::pdrQueryTraceHistory(
                query.fromUnixMicroseconds, query.toUnixMicroseconds,
                query.businessName.c_str(), query.status.c_str(), query.limit,
                query.offset, append, records.get());
            Poco::JSON::Object root;
            root.set("records", records);
            root.set("hasMore", hasMore);
            root.set("limit", query.limit);
            root.set("offset", query.offset);
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentType("application/json; charset=utf-8");
            response.set("Cache-Control", "no-store");
            root.stringify(response.send());
        }
        catch (const std::exception& exception)
        {
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                          exception.what());
        }
    }
};

class StaticHealthContributor final : public PocoDDS::Health::IHealthContributor
{
public:
    explicit StaticHealthContributor(PocoDDS::Health::Report report):
        _report(std::move(report))
    {
    }
    PocoDDS::Health::Report health() const override { return _report; }
private:
    PocoDDS::Health::Report _report;
};

const char* healthStatusName(PocoDDS::Health::Status status)
{
    switch (status)
    {
    case PocoDDS::Health::Status::up: return "UP";
    case PocoDDS::Health::Status::degraded: return "DEGRADED";
    case PocoDDS::Health::Status::down: return "DOWN";
    }
    return "DOWN";
}

class HealthHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit HealthHandler(Poco::OSP::BundleContext::Ptr context):
        _context(std::move(context))
    {
    }

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        PocoDDS::Health::HealthRegistry registry;
        registry.add(std::make_shared<StaticHealthContributor>(
            PocoDDS::Health::Report{"runtime", PocoDDS::Health::Status::up, "HTTP server active"}));

        std::vector<Poco::OSP::Bundle::Ptr> bundles;
        _context->listBundles(bundles);
        std::size_t activeBundles = 0;
        for (const auto& bundle : bundles)
            if (bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE)
                ++activeBundles;
        const bool bundlesUp = activeBundles > 0;
        registry.add(std::make_shared<StaticHealthContributor>(
            PocoDDS::Health::Report{
                "bundles",
                bundlesUp ? PocoDDS::Health::Status::up : PocoDDS::Health::Status::down,
                std::to_string(activeBundles) + "/" + std::to_string(bundles.size()) + " active",
                bundlesUp ? "" : "PDR-HEALTH-BUNDLE-NONE_ACTIVE",
                bundlesUp ? "" : "Inspect Bundle startup logs and required Bundle dependencies."}));

        if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
        {
            const auto processes = manager->processes();
            const auto required = static_cast<std::size_t>(std::count_if(
                processes.begin(), processes.end(),
                [](const auto& process) { return process.required; }));
            const auto runningRequired = static_cast<std::size_t>(std::count_if(
                processes.begin(), processes.end(), [](const auto& process) {
                    return process.required && process.state == "running";
                }));
            std::vector<std::string> affected;
            for (const auto& process : processes)
                if (process.required && process.state != "running") affected.push_back(process.name);
            const bool requiredRunning = runningRequired == required;
            registry.add(std::make_shared<StaticHealthContributor>(
                PocoDDS::Health::Report{
                    "subprocesses",
                    requiredRunning ? PocoDDS::Health::Status::up
                                    : PocoDDS::Health::Status::degraded,
                    std::to_string(manager->runningCount()) + "/" +
                        std::to_string(processes.size()) + " running, " +
                        std::to_string(runningRequired) + "/" +
                        std::to_string(required) + " required",
                    requiredRunning ? "" : "PDR-HEALTH-SUBPROCESS-REQUIRED_NOT_RUNNING",
                    requiredRunning ? "" : "Inspect the affected process log, then restart it from process management.",
                    std::move(affected)}));
        }
        else
        {
            registry.add(std::make_shared<StaticHealthContributor>(
                PocoDDS::Health::Report{"subprocesses", PocoDDS::Health::Status::degraded,
                                        "manager not initialized",
                                        "PDR-HEALTH-SUBPROCESS-MANAGER_UNAVAILABLE",
                                        "Verify ProcessManagement Bundle startup and Runtime configuration."}));
        }

        const auto protocolServices = _context->registry().find("pdr.protocol");
        std::size_t openProtocols = 0;
        std::size_t requiredProtocols = 0;
        std::size_t openRequiredProtocols = 0;
        std::vector<std::string> affectedProtocols;
        for (const auto& service : protocolServices)
        {
            const bool required =
                service->properties().getBool("pdr.protocol.required", false);
            if (required) ++requiredProtocols;
            try
            {
                const auto provider =
                    service->castedInstance<PocoDDS::Protocols::ProtocolService>();
                if (provider->isOpen())
                {
                    ++openProtocols;
                    if (required) ++openRequiredProtocols;
                }
                else if (required)
                    affectedProtocols.push_back(service->properties().get(
                        "pdr.protocol.id", service->name()));
            }
            catch (...)
            {
                if (required) affectedProtocols.push_back(service->properties().get(
                    "pdr.protocol.id", service->name()));
            }
        }
        const bool protocolsReady = openRequiredProtocols == requiredProtocols;
        registry.add(std::make_shared<StaticHealthContributor>(
            PocoDDS::Health::Report{
                "protocols",
                protocolsReady ? PocoDDS::Health::Status::up
                               : PocoDDS::Health::Status::degraded,
                std::to_string(openProtocols) + "/" +
                    std::to_string(protocolServices.size()) + " open; " +
                    std::to_string(openRequiredProtocols) + "/" +
                    std::to_string(requiredProtocols) + " required open",
                protocolsReady ? "" : "PDR-HEALTH-PROTOCOL-REQUIRED_CLOSED",
                protocolsReady ? "" : "Inspect protocol diagnostics and endpoint connectivity, then restart the affected instance.",
                std::move(affectedProtocols)}));

        const auto deviceServices = _context->registry().find("pdr.device");
        std::size_t requiredDevices = 0;
        std::size_t readyDevices = 0;
        std::size_t faultDevices = 0;
        std::vector<std::string> affectedDevices;
        for (const auto& service : deviceServices)
        {
            if (!service->properties().getBool("pdr.deviceRequired", true)) continue;
            ++requiredDevices;
            try
            {
                const auto provider = service->castedInstance<PocoDDS::Devices::DeviceService>();
                const auto state = provider->device().snapshot().state;
                if (state == PocoDDS::Devices::DeviceState::ready) ++readyDevices;
                else
                {
                    if (state == PocoDDS::Devices::DeviceState::fault) ++faultDevices;
                    affectedDevices.push_back(service->properties().get(
                        "pdr.device", service->name()));
                }
            }
            catch (...)
            {
                ++faultDevices;
                affectedDevices.push_back(service->properties().get(
                    "pdr.device", service->name()));
            }
        }
        if (requiredDevices > 0)
        {
            const bool devicesReady = readyDevices == requiredDevices;
            registry.add(std::make_shared<StaticHealthContributor>(
                PocoDDS::Health::Report{
                    "devices", devicesReady ? PocoDDS::Health::Status::up
                                            : PocoDDS::Health::Status::degraded,
                    std::to_string(readyDevices) + "/" + std::to_string(requiredDevices) +
                        " required ready, " + std::to_string(faultDevices) + " fault",
                    devicesReady ? "" : "PDR-HEALTH-DEVICE-REQUIRED_NOT_READY",
                    devicesReady ? "" : "Open device diagnostics, inspect the last error, then verify wiring and transport.",
                    std::move(affectedDevices)}));
        }

        registry.add(std::make_shared<StaticHealthContributor>(managementTaskHealthReport()));

        const auto report = registry.collect();
        for (const auto& component : report.components)
        {
            PocoDDS::Observability::MetricAttributes attributes{
                {"component", component.component},
                {"status", healthStatusName(component.status)}};
            if (!component.code.empty()) attributes.emplace("code", component.code);
            PocoDDS::Observability::Metrics::global().addCounter(
                "pdr.health.component.samples", 1, std::move(attributes),
                "Health probe samples by component, status and stable fault code", "{sample}");
        }
        const std::string path = Poco::URI(request.getURI()).getPath();
        const bool liveness = path == "/health/live";
        const bool readiness = path == "/health/ready";
        if (path != "/health" && path != "/health/" && !liveness && !readiness &&
            path != "/health/detail")
        {
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                          "unknown health endpoint");
            return;
        }

        Poco::JSON::Object root;
        root.set("status", healthStatusName(report.status));
        root.set("live", report.live());
        root.set("ready", report.ready());
        if (!liveness && !readiness)
        {
            Poco::JSON::Array components;
            for (const auto& component : report.components)
            {
                Poco::JSON::Object item;
                item.set("name", component.component);
                item.set("status", healthStatusName(component.status));
                item.set("detail", component.detail);
                if (!component.code.empty()) item.set("code", component.code);
                if (!component.remediation.empty()) item.set("remediation", component.remediation);
                Poco::JSON::Array affected;
                for (const auto& instance : component.affected) affected.add(instance);
                item.set("affected", affected);
                components.add(item);
            }
            root.set("components", components);
            root.set("schemaVersion", 2);
        }
        const bool acceptable = liveness ? report.live() : (readiness ? report.ready() : true);
        response.setStatus(acceptable ? Poco::Net::HTTPResponse::HTTP_OK
                                      : Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};
} // namespace

class HealthHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new HealthHandler(context());
    }
};

class MetricsHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new MetricsHandler(context());
    }
};

class OpenTelemetryMetricsHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new OpenTelemetryMetricsHandler;
    }
};

class DevicesHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new DevicesHandler(context());
    }
};

class DiagnosticEventsHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new DiagnosticEventsHandler;
    }
};

class AlertsHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new AlertsHandler;
    }
};

class AlertHistoryHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new AlertHistoryHandler(context());
    }
};

class AlertSinksHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new AlertSinksHandler(context());
    }
};

class ProtocolsHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ProtocolsHandler(context());
    }
};

class ProcessLogsHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ProcessLogsHandler;
    }
};

class ProcessDetailHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ProcessDetailHandler(context());
    }
};

class BundleLifecycleHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new BundleLifecycleHandler(context());
    }
};

class ProcessLifecycleHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ProcessLifecycleHandler;
    }
};

class ProcessConfigHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ProcessConfigHandler(context());
    }
};

class ManagementAuditHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ManagementAuditHandler;
    }
};

class IdentityHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new IdentityHandler(context());
    }
};

class ManagementTasksHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ManagementTasksHandler;
    }
};

class BusinessTracesHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new BusinessTracesHandler;
    }
};

class HeartbeatBusinessHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new HeartbeatBusinessHandler;
    }
};

class BusinessTraceHistoryHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new BusinessTraceHistoryHandler;
    }
};

class BundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        const auto preferencesRef = context->registry().findByName(
            Poco::OSP::PreferencesService::SERVICE_NAME);
        Poco::AutoPtr<Poco::Util::AbstractConfiguration> config =
            preferencesRef->castedInstance<Poco::OSP::PreferencesService>()->configuration();
        configureManageableBundles(config->getString(
            "pdr.management.manageableBundles", DEFAULT_MANAGEABLE_BUNDLES));
        pluginQuarantineManager().configure(*config, context);
        _context = context;
        context->events().bundleFailed += Poco::delegate(this, &BundleActivator::onBundleFailed);
        context->events().bundleStarted += Poco::delegate(this, &BundleActivator::onBundleStarted);
        configureManagementAuthorization(*config, context);
        configureManagementRequestLedger(*config);
        managementTaskManager().start(
            static_cast<std::size_t>(std::max(1,
                config->getInt("pdr.management.tasks.workerCount", 2))),
            static_cast<std::size_t>(std::max(1,
                config->getInt("pdr.management.tasks.capacity", 100))),
            static_cast<std::size_t>(std::max(1,
                config->getInt("pdr.management.tasks.retention", 1000))),
            std::max(1, config->getInt(
                "pdr.management.tasks.health.degradedWaitMilliseconds", 30000)),
            config->getBool("pdr.management.tasks.persistence.enabled", true),
            Poco::Path(config->expand(config->getString(
                "pdr.management.tasks.persistence.path",
                "${application.dir}management-tasks.json"))).makeAbsolute());
        Poco::OSP::Properties taskHealthProperties;
        taskHealthProperties.set("pdr.healthContributor", "true");
        taskHealthProperties.set("pdr.healthContributor.component", "management-tasks");
        _taskHealthServiceRef = context->registry().registerService(
            "pdr.health.managementTasks", new ManagementTaskHealthService,
            taskHealthProperties);
        AlertPolicy alertPolicy;
        alertPolicy.debounceMicroseconds = 1000LL * std::max(0,
            config->getInt("pdr.alerts.debounceMilliseconds", 1000));
        alertPolicy.escalationMicroseconds = 1000LL * std::max(0,
            config->getInt("pdr.alerts.escalationMilliseconds", 300000));
        alertPolicy.retention = static_cast<std::size_t>(std::max(1,
            config->getInt("pdr.alerts.retention", 500)));
        std::istringstream silences(config->getString("pdr.alerts.silencedCodes", ""));
        std::string silence;
        while (std::getline(silences, silence, ','))
        {
            silence.erase(0, silence.find_first_not_of(" \t"));
            const auto end = silence.find_last_not_of(" \t");
            if (end != std::string::npos) silence.erase(end + 1);
            if (!silence.empty()) alertPolicy.silencedCodes.push_back(silence);
        }
        diagnosticEvents().configure(std::move(alertPolicy));
        const auto deliveryQueueCapacity = static_cast<std::size_t>(std::max(1,
            config->getInt("pdr.alerts.deliveryQueueCapacity", 1000)));
        const auto deliveryFailureThreshold = static_cast<std::uint64_t>(std::max(1,
            config->getInt("pdr.alerts.deliveryFailureThreshold", 5)));
        const auto deliveryCircuitOpenMicroseconds = 1000LL * std::max(1,
            config->getInt("pdr.alerts.deliveryCircuitOpenMilliseconds", 30000));
        if (config->getBool("pdr.alerts.history.enabled", true))
        {
            try
            {
                const auto historyPath = config->expand(config->getString(
                    "pdr.alerts.history.path", "${application.dir}data/alerts/alerts.jsonl"));
                const auto maximumBytes = static_cast<std::size_t>(std::max<Poco::Int64>(1024,
                    config->getInt64("pdr.alerts.history.maximumBytes", 10485760)));
                _historySink = new JsonlAlertSinkService(historyPath, maximumBytes);
                Poco::OSP::Properties sinkProperties;
                sinkProperties.set("pdr.alertSink", "true");
                sinkProperties.set("pdr.alertSink.name", "local-history");
                sinkProperties.set("pdr.alertSink.type", "jsonl-history");
                sinkProperties.set("pdr.alertSink.receiveSilenced", "true");
                _historySinkRef = context->registry().registerService(
                    "pdr.alertSink.localHistory", _historySink, sinkProperties);
            }
            catch (const std::exception& exception)
            {
                context->logger().error(
                    "Alert history disabled after initialization failure: " +
                    std::string(exception.what()));
                PocoDDS::Observability::Metrics::global().addCounter(
                    "pdr.alert.delivery", 1,
                    {{"result", "error"}, {"sink", "local-history-init"}});
                _historySink = nullptr;
            }
        }
        alertDispatcher().start(context, deliveryQueueCapacity,
                                deliveryFailureThreshold,
                                deliveryCircuitOpenMicroseconds);
        _service = new SystemMonitoringService;
        Poco::OSP::Properties properties;
        properties.set("pdr.service", "systemMonitoring");
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        _serviceRef = context->registry().registerService(SERVICE_NAME, _service, properties);
        _service->start();
        _monitoring = true;
        _diagnosticMonitor = std::thread([this, context] { monitorDiagnostics(context); });
        context->logger().information(
            "System monitoring started: CPU, memory, disk, network and threads.");
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        context->events().bundleFailed -= Poco::delegate(this, &BundleActivator::onBundleFailed);
        context->events().bundleStarted -= Poco::delegate(this, &BundleActivator::onBundleStarted);
        _context = nullptr;
        _monitoring = false;
        if (_diagnosticMonitor.joinable()) _diagnosticMonitor.join();
        if (_taskHealthServiceRef)
            context->registry().unregisterService(_taskHealthServiceRef);
        _taskHealthServiceRef = nullptr;
        managementTaskManager().stop();
        alertDispatcher().stop();
        if (_historySinkRef) context->registry().unregisterService(_historySinkRef);
        _historySinkRef = nullptr;
        _historySink = nullptr;
        if (_service)
            _service->stop();
        if (_serviceRef)
            context->registry().unregisterService(_serviceRef);
        _serviceRef = nullptr;
        _service = nullptr;
    }

private:
    void onBundleFailed(const void*, Poco::OSP::BundleEvent& event)
    {
        if (!_context) return;
        const std::string id = event.bundle()->symbolicName();
        auto bundle = _context->findBundle(id);
        if (!bundle) return;
        const auto* exception = event.exception();
        pluginQuarantineManager().failure(
            bundle, exception ? exception->displayText() : "unknown bundle start failure");
    }

    void onBundleStarted(const void*, Poco::OSP::BundleEvent& event)
    {
        if (!_context) return;
        auto bundle = _context->findBundle(event.bundle()->symbolicName());
        if (bundle) pluginQuarantineManager().success(bundle);
    }

    void monitorDiagnostics(Poco::OSP::BundleContext::Ptr context)
    {
        while (_monitoring.load())
        {
            for (const auto& service : context->registry().find("pdr.device"))
            {
                try
                {
                    const auto provider =
                        service->castedInstance<PocoDDS::Devices::DeviceService>();
                    if (const auto* diagnostic =
                            dynamic_cast<const PocoDDS::Devices::FailureDiagnosticDevice*>(
                                &provider->device()))
                        diagnosticEvents().observe(
                            context->logger(), "device",
                            service->properties().get("pdr.device", service->name()),
                            diagnostic->failure());
                }
                catch (...) {}
            }
            for (const auto& service : context->registry().find("pdr.protocol"))
            {
                try
                {
                    const auto provider =
                        service->castedInstance<PocoDDS::Protocols::ProtocolService>();
                    static_cast<void>(provider->diagnostics());
                    diagnosticEvents().observe(
                        context->logger(), "protocol",
                        service->properties().get("pdr.protocol.id", service->name()),
                        provider->failure());
                }
                catch (...) {}
            }
            for (int wait = 0; wait < 20 && _monitoring.load(); ++wait)
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }

    Poco::AutoPtr<SystemMonitoringService> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::AutoPtr<JsonlAlertSinkService> _historySink;
    Poco::OSP::ServiceRef::Ptr _historySinkRef;
    Poco::OSP::ServiceRef::Ptr _taskHealthServiceRef;
    Poco::OSP::BundleContext::Ptr _context;
    std::atomic<bool> _monitoring{false};
    std::thread _diagnosticMonitor;
};
} // namespace PocoDDS::SystemMonitoring

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::BundleActivator)
POCO_END_MANIFEST

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::MetricsHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::OpenTelemetryMetricsHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::DevicesHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::DiagnosticEventsHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::AlertsHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::AlertHistoryHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::AlertSinksHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::ProtocolsHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::ProcessLogsHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::ProcessDetailHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::ProcessLifecycleHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::BundleLifecycleHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::ProcessConfigHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::ManagementAuditHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::IdentityHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::ManagementTasksHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::BusinessTracesHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::BusinessTraceHistoryHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::HeartbeatBusinessHandlerFactory)
POCO_END_MANIFEST
