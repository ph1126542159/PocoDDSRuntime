#include "PocoDDS/Configuration/ConfigurationValidator.h"
#include "PocoDDS/Security/PrincipalStore.h"
#include "PocoDDS/Configuration/IndexedConfiguration.h"

#include "Poco/Exception.h"
#include "Poco/Environment.h"
#include "Poco/NumberParser.h"
#include "Poco/URI.h"
#include "Poco/Util/AbstractConfiguration.h"

#include <sstream>
#include <algorithm>
#include <cctype>
#include <exception>
#include <regex>
#include <unordered_set>

namespace PocoDDS::Configuration
{
namespace
{
void requireString(const Poco::Util::AbstractConfiguration& config,
                   const std::string& key,
                   std::vector<ValidationIssue>& issues)
{
    if (!config.hasProperty(key) || config.getString(key, "").empty())
        issues.push_back({key, "required non-empty string"});
}

void integerRange(const Poco::Util::AbstractConfiguration& config,
                  const std::string& key,
                  int minimum,
                  int maximum,
                  bool required,
                  std::vector<ValidationIssue>& issues)
{
    if (!config.hasProperty(key))
    {
        if (required)
            issues.push_back({key, "required integer"});
        return;
    }
    int value = 0;
    if (!Poco::NumberParser::tryParse(config.getString(key), value))
    {
        issues.push_back({key, "must be an integer"});
        return;
    }
    if (value < minimum || value > maximum)
        issues.push_back(
            {key, "must be in range " + std::to_string(minimum) + ".." +
                      std::to_string(maximum)});
}

void allowedString(const Poco::Util::AbstractConfiguration& config,
                   const std::string& key,
                   const std::unordered_set<std::string>& allowed,
                   std::vector<ValidationIssue>& issues)
{
    if (!config.hasProperty(key))
        return;
    const auto value = config.getString(key);
    if (allowed.find(value) == allowed.end())
        issues.push_back({key, "unsupported value " + value});
}

void serialParameters(const Poco::Util::AbstractConfiguration& config,
                      const std::string& key,
                      std::vector<ValidationIssue>& issues)
{
    if (config.hasProperty(key) &&
        !std::regex_match(config.getString(key), std::regex("[5-8][NEO][12]")))
        issues.push_back({key, "must match data/parity/stop format such as 8N1 or 7E1"});
}

bool isLoopbackHost(std::string host)
{
    std::transform(host.begin(), host.end(), host.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    return host == "127.0.0.1" || host == "::1" || host == "localhost";
}

void bundleManagementPatterns(const Poco::Util::AbstractConfiguration& config,
                              std::vector<ValidationIssue>& issues)
{
    const std::string key = "pdr.management.manageableBundles";
    if (!config.hasProperty(key)) return;
    std::istringstream stream(config.getString(key));
    std::string pattern;
    std::unordered_set<std::string> unique;
    while (std::getline(stream, pattern, ','))
    {
        pattern.erase(0, pattern.find_first_not_of(" \t"));
        const auto end = pattern.find_last_not_of(" \t");
        if (end != std::string::npos) pattern.erase(end + 1);
        if (pattern.empty()) continue;
        if (pattern == "*" ||
            !std::regex_match(pattern, std::regex("[A-Za-z0-9][A-Za-z0-9_.-]*\\*?")) ||
            (pattern.find('*') != std::string::npos && pattern.back() != '*'))
        {
            issues.push_back({key,
                "entries must be exact Bundle IDs or non-global prefixes ending in *: " +
                pattern});
        }
        else if (!unique.insert(pattern).second)
            issues.push_back({key, "duplicate Bundle pattern " + pattern});
    }
}
}

std::vector<ValidationIssue> ConfigurationValidator::validate(
    const Poco::Util::AbstractConfiguration& config) const
{
    std::vector<ValidationIssue> issues;
    allowedString(config, "logging.loggers.root.level",
                  {"fatal", "critical", "error", "warning", "notice",
                   "information", "debug", "trace"}, issues);
    requireString(config, "osp.web.server.host", issues);
    integerRange(config, "osp.web.server.port", 1, 65535, true, issues);
    integerRange(config, "pdr.fastdds.domainId", 0, 232, true, issues);
    integerRange(config, "pdr.subprocess.shutdownTimeoutMilliseconds", 1, 3600000, true, issues);
    bundleManagementPatterns(config, issues);
    const bool managementAuthenticationRequired =
        config.getBool("pdr.management.authentication.required", false);
    const bool managementRequestIdRequired =
        config.getBool("pdr.management.idempotency.requireRequestId", false);
    const std::string managementTokenEnvironment =
        config.getString("pdr.management.authentication.tokenEnvironment", "");
    const std::string managementTokenFile =
        config.getString("pdr.management.authentication.tokenFile", "");
    integerRange(config, "pdr.management.authentication.principals.count", 0, 64, false,
                 issues);
    int managementPrincipalCount = 0;
    try
    {
        managementPrincipalCount =
            config.getInt("pdr.management.authentication.principals.count", 0);
    }
    catch (...) {}
    if (managementAuthenticationRequired && managementTokenEnvironment.empty() &&
        managementTokenFile.empty() &&
        managementPrincipalCount == 0)
        issues.push_back({"pdr.management.authentication.tokenEnvironment",
                          "or at least one principal is required when management authentication is enabled"});
    if (!managementTokenEnvironment.empty() && !managementTokenFile.empty())
        issues.push_back({"pdr.management.authentication.tokenFile",
                          "configure exactly one of tokenEnvironment or tokenFile"});
    else if (!managementTokenEnvironment.empty())
    {
        if (!std::regex_match(managementTokenEnvironment,
                              std::regex("[A-Za-z_][A-Za-z0-9_]*")))
            issues.push_back({"pdr.management.authentication.tokenEnvironment",
                              "must be a valid environment variable name"});
        else if (!Poco::Environment::has(managementTokenEnvironment) ||
                 Poco::Environment::get(managementTokenEnvironment).empty())
            issues.push_back({"pdr.management.authentication.tokenEnvironment",
                              "environment variable is not set or empty: " +
                                  managementTokenEnvironment});
    }
    const std::unordered_set<std::string> allowedManagementPermissions{
        "protocol.manage", "process.manage", "bundle.manage", "configuration.manage",
        "identity.manage", "audit.read", "task.read", "task.cancel",
        "diagnostics.read", "diagnostics.execute"};
    std::unordered_set<std::string> principalIds;
    std::unordered_set<std::string> principalTokenEnvironments;
    std::unordered_set<std::string> principalTokenValues;
    if (!managementTokenEnvironment.empty())
    {
        principalIds.insert("legacy-admin");
        principalTokenEnvironments.insert(managementTokenEnvironment);
        if (Poco::Environment::has(managementTokenEnvironment))
        {
            const std::string value = Poco::Environment::get(managementTokenEnvironment);
            if (!value.empty()) principalTokenValues.insert(value);
        }
    }
    for (int index = 0; index < managementPrincipalCount && index < 64; ++index)
    {
        const std::string prefix = "pdr.management.authentication.principals." +
            std::to_string(index) + ".";
        const std::string id = config.getString(prefix + "id", "");
        const std::string tokenEnvironment =
            config.getString(prefix + "tokenEnvironment", "");
        const std::string tokenFile = config.getString(prefix + "tokenFile", "");
        const std::string permissions = config.getString(prefix + "permissions", "");
        if (!std::regex_match(id, std::regex("[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")))
            issues.push_back({prefix + "id", "must be a 1-64 character principal ID"});
        else if (!principalIds.insert(id).second)
            issues.push_back({prefix + "id", "duplicate management principal ID " + id});
        if (tokenEnvironment.empty() == tokenFile.empty())
            issues.push_back({prefix + "tokenEnvironment",
                              "configure exactly one of tokenEnvironment or tokenFile"});
        else if (!tokenEnvironment.empty() && !std::regex_match(tokenEnvironment,
                               std::regex("[A-Za-z_][A-Za-z0-9_]*")))
            issues.push_back({prefix + "tokenEnvironment",
                              "must be a valid environment variable name"});
        else if (!tokenEnvironment.empty() &&
                 !principalTokenEnvironments.insert(tokenEnvironment).second)
            issues.push_back({prefix + "tokenEnvironment",
                              "duplicate management token environment"});
        else if (!tokenEnvironment.empty() && (!Poco::Environment::has(tokenEnvironment) ||
                 Poco::Environment::get(tokenEnvironment).empty())
                )
            issues.push_back({prefix + "tokenEnvironment",
                              "environment variable is not set or empty: " + tokenEnvironment});
        else if (!tokenEnvironment.empty() &&
                 !principalTokenValues.insert(Poco::Environment::get(tokenEnvironment)).second)
            issues.push_back({prefix + "tokenEnvironment",
                              "duplicates another management bearer token value"});
        std::istringstream permissionStream(permissions);
        std::string permission;
        bool hasPermission = false;
        while (std::getline(permissionStream, permission, ','))
        {
            permission.erase(permission.begin(),
                std::find_if(permission.begin(), permission.end(), [](unsigned char ch) {
                    return !std::isspace(ch);
                }));
            permission.erase(std::find_if(permission.rbegin(), permission.rend(),
                [](unsigned char ch) { return !std::isspace(ch); }).base(), permission.end());
            if (permission.empty()) continue;
            hasPermission = true;
            if (permission != "*" && allowedManagementPermissions.count(permission) == 0)
                issues.push_back({prefix + "permissions",
                                  "unknown management permission " + permission});
        }
        if (!hasPermission)
            issues.push_back({prefix + "permissions", "requires at least one permission"});
    }
    try
    {
        static_cast<void>(
            PocoDDS::Security::PrincipalStore::fromManagementConfiguration(config));
    }
    catch (const Poco::Exception& exception)
    {
        issues.push_back({"pdr.management.authentication", exception.displayText()});
    }
    const bool managementAuditEnabled = config.getBool("pdr.management.audit.enabled", true);
    if (managementAuditEnabled &&
        config.getString("pdr.management.audit.path", "management-audit.jsonl").empty())
        issues.push_back({"pdr.management.audit.path",
                          "is required when management audit is enabled"});
    integerRange(config, "pdr.management.audit.maximumBytes", 1024, 1073741824, false,
                 issues);
    integerRange(config, "pdr.management.idempotency.retention", 1, 100000, false, issues);
    integerRange(config, "pdr.management.idempotency.ttlMilliseconds",
                 1000, 2147483647, false, issues);
    if (config.getBool("pdr.management.idempotency.persistence.enabled", true) &&
        config.getString("pdr.management.idempotency.persistence.path",
                         "management-idempotency.json").empty())
        issues.push_back({"pdr.management.idempotency.persistence.path",
                          "is required when management idempotency persistence is enabled"});
    integerRange(config, "pdr.management.tasks.workerCount", 1, 8, false, issues);
    integerRange(config, "pdr.management.tasks.capacity", 1, 10000, false, issues);
    integerRange(config, "pdr.management.tasks.retention", 1, 100000, false, issues);
    integerRange(config, "pdr.management.tasks.health.degradedWaitMilliseconds",
                 1, 3600000, false, issues);
    if (config.getBool("pdr.management.tasks.persistence.enabled", true) &&
        config.getString("pdr.management.tasks.persistence.path", "management-tasks.json").empty())
        issues.push_back({"pdr.management.tasks.persistence.path",
                          "is required when management task persistence is enabled"});
    integerRange(config, "pdr.plugins.quarantine.failureThreshold", 1, 1000, false, issues);
    if (config.getBool("pdr.plugins.quarantine.enabled", true) &&
        config.getString("pdr.plugins.quarantine.path",
                         "data/plugin-quarantine.json").empty())
        issues.push_back({"pdr.plugins.quarantine.path",
                          "is required when plugin quarantine is enabled"});
    integerRange(config, "pdr.alerts.debounceMilliseconds", 0, 604800000, false, issues);
    integerRange(config, "pdr.alerts.escalationMilliseconds", 0, 604800000, false, issues);
    integerRange(config, "pdr.alerts.retention", 1, 100000, false, issues);
    integerRange(config, "pdr.alerts.deliveryQueueCapacity", 1, 100000, false, issues);
    integerRange(config, "pdr.alerts.deliveryFailureThreshold", 1, 1000, false, issues);
    integerRange(config, "pdr.alerts.deliveryCircuitOpenMilliseconds",
                 100, 3600000, false, issues);
    integerRange(config, "pdr.alerts.history.maximumBytes", 1024, 1073741824, false, issues);
    if (config.hasProperty("pdr.alerts.history.enabled") &&
        config.getBool("pdr.alerts.history.enabled"))
    {
        const std::string path = config.getString("pdr.alerts.history.path", "");
        if (path.empty())
            issues.push_back({"pdr.alerts.history.path",
                              "is required when pdr.alerts.history.enabled is true"});
    }
    integerRange(config, "pdr.alerts.webhook.count", 0, 256, false, issues);
    std::vector<IndexedInstance> webhookInstances;
    try
    {
        webhookInstances = indexedInstances(
            config, "pdr.alerts.webhook", false, 0, "webhook");
    }
    catch (const std::exception& exception)
    {
        issues.push_back({"pdr.alerts.webhook", exception.what()});
    }
    for (const auto& instance : webhookInstances)
    {
        const std::string prefix = instance.prefix + ".";
        integerRange(config, prefix + "timeoutMilliseconds", 100, 60000, false, issues);
        integerRange(config, prefix + "maximumAttempts", 1, 10, false, issues);
        integerRange(config, prefix + "initialBackoffMilliseconds", 0, 60000, false, issues);
        integerRange(config, prefix + "maximumBackoffMilliseconds", 0, 60000, false, issues);
        if (!instance.enabled) continue;
        requireString(config, prefix + "url", issues);
        const std::string url = config.getString(prefix + "url", "");
        bool https = false;
        try
        {
            const Poco::URI uri(url);
            https = uri.getScheme() == "https";
            if ((uri.getScheme() != "http" && !https) || uri.getHost().empty())
                issues.push_back({prefix + "url", "must be an HTTP(S) URL with a host"});
        }
        catch (const Poco::Exception&)
        {
            issues.push_back({prefix + "url", "must be a valid HTTP(S) URL"});
        }
        const auto validateSecretEnvironment = [&](const std::string& key) {
            const auto variable = config.getString(key, "");
            if (variable.empty()) return;
            if (!std::regex_match(variable, std::regex("[A-Za-z_][A-Za-z0-9_]*")))
                issues.push_back({key, "must be a valid environment variable name"});
            else if (!Poco::Environment::has(variable) || Poco::Environment::get(variable).empty())
                issues.push_back({key, "environment variable is not set or empty: " + variable});
        };
        validateSecretEnvironment(prefix + "authorizationEnvironment");
        validateSecretEnvironment(prefix + "privateKeyPasswordEnvironment");
        const bool certificate = !config.getString(prefix + "clientCertificate", "").empty();
        const bool privateKey = !config.getString(prefix + "privateKey", "").empty();
        if (certificate != privateKey)
            issues.push_back({prefix + (certificate ? "privateKey" : "clientCertificate"),
                              "clientCertificate and privateKey must be configured together"});
        const bool tlsMaterial = certificate || privateKey ||
            !config.getString(prefix + "caCertificate", "").empty() ||
            config.getBool(prefix + "insecureSkipVerify", false);
        if (tlsMaterial && !https)
            issues.push_back({prefix + "url", "TLS options require an HTTPS URL"});
        if (config.getString("security.profile", "development") == "production" &&
            config.getBool(prefix + "insecureSkipVerify", false))
            issues.push_back({prefix + "insecureSkipVerify", "must be false in production"});
        int initial = 200;
        int maximum = 2000;
        const bool initialValid = Poco::NumberParser::tryParse(
            config.getString(prefix + "initialBackoffMilliseconds", "200"), initial);
        const bool maximumValid = Poco::NumberParser::tryParse(
            config.getString(prefix + "maximumBackoffMilliseconds", "2000"), maximum);
        if (initialValid && maximumValid && maximum < initial)
            issues.push_back({prefix + "maximumBackoffMilliseconds",
                              "must be greater than or equal to initialBackoffMilliseconds"});
    }
    try
    {
        if (config.hasProperty("pdr.alerts.debounceMilliseconds") &&
            config.hasProperty("pdr.alerts.escalationMilliseconds") &&
            config.getInt64("pdr.alerts.escalationMilliseconds") <
                config.getInt64("pdr.alerts.debounceMilliseconds"))
            issues.push_back({"pdr.alerts.escalationMilliseconds",
                              "must be greater than or equal to pdr.alerts.debounceMilliseconds"});
    }
    catch (const Poco::Exception&) {}
    integerRange(config, "observability.history.retentionDays", 1, 36500, false, issues);
    integerRange(config, "observability.metrics.exportIntervalMilliseconds", 100, 3600000, false, issues);
    integerRange(config, "observability.metrics.exportTimeoutMilliseconds", 100, 3600000, false, issues);
    integerRange(config, "observability.metrics.maximumSeries", 1, 1000000, false, issues);
    integerRange(config, "observability.metrics.offlineCacheMaximumFiles", 1, 1000000, false, issues);
    integerRange(config, "pdr.modbus.port", 1, 65535, false, issues);
    integerRange(config, "pdr.modbus.unitId", 0, 247, false, issues);
    integerRange(config, "pdr.serial.baudRate", 1, 4000000, false, issues);
    integerRange(config, "pdr.gnss.baudRate", 1, 4000000, false, issues);
    const auto validateFamily = [&](const std::string& base,
                                    bool legacyEnabled,
                                    std::size_t defaultCount,
                                    const std::string& idPrefix) {
        integerRange(config, base + ".count", 0, 256, false, issues);
        try
        {
            return indexedInstances(config, base, legacyEnabled, defaultCount, idPrefix);
        }
        catch (const std::exception& exception)
        {
            issues.push_back({base, exception.what()});
            return std::vector<IndexedInstance>{};
        }
    };
    std::unordered_set<std::string> deviceIds;
    const auto validateId = [&](const IndexedInstance& instance,
                                const std::string& base) {
        if (!instance.enabled)
            return;
        if (instance.id.empty())
            issues.push_back({instance.prefix + ".id", "required non-empty string"});
        else if (!deviceIds.insert(instance.id).second)
            issues.push_back({instance.prefix + ".id", "duplicate device id " + instance.id});
        (void) base;
    };

    for (const auto& instance : validateFamily("pdr.simulation", true, 1, "simulation"))
        validateId(instance, "pdr.simulation");
    for (const auto& instance : validateFamily("pdr.modbus", false, 0, "modbus"))
    {
        validateId(instance, "pdr.modbus");
        if (!instance.enabled) continue;
        integerRange(config, instance.prefix + ".port", 1, 65535, false, issues);
        integerRange(config, instance.prefix + ".unitId", 0, 247, false, issues);
        integerRange(config, instance.prefix + ".timeoutMilliseconds", 1, 60000, false, issues);
        integerRange(config, instance.prefix + ".readRetryAttempts", 0, 10, false, issues);
        integerRange(config, instance.prefix + ".retryDelayMilliseconds", 0, 60000, false, issues);
    }
    for (const auto& instance : validateFamily("pdr.serial", false, 0, "serial"))
    {
        validateId(instance, "pdr.serial");
        if (!instance.enabled) continue;
        const auto transport =
            config.getString(instance.prefix + ".transport", "port");
        allowedString(config, instance.prefix + ".transport", {"port", "loopback"}, issues);
        if (transport == "port")
            requireString(config, instance.prefix + ".port", issues);
        integerRange(config, instance.prefix + ".baudRate", 1, 4000000, false, issues);
        serialParameters(config, instance.prefix + ".parameters", issues);
        allowedString(config, instance.prefix + ".flowControl", {"none", "rtscts"}, issues);
        integerRange(config, instance.prefix + ".reconnectDelayMilliseconds", 0, 60000, false, issues);
        integerRange(config, instance.prefix + ".readTimeoutMilliseconds", 1, 60000, false, issues);
    }
    for (const auto& instance : validateFamily("pdr.gnss", false, 0, "gnss"))
    {
        validateId(instance, "pdr.gnss");
        if (!instance.enabled) continue;
        const auto transport = config.getString(instance.prefix + ".transport", "port");
        allowedString(config, instance.prefix + ".transport", {"port", "loopback"}, issues);
        if (transport == "port") requireString(config, instance.prefix + ".port", issues);
        integerRange(config, instance.prefix + ".baudRate", 1, 4000000, false, issues);
        integerRange(config, instance.prefix + ".reconnectDelayMilliseconds", 0, 60000, false, issues);
        integerRange(config, instance.prefix + ".readTimeoutMilliseconds", 1, 60000, false, issues);
        integerRange(config, instance.prefix + ".staleAfterMilliseconds", 1, 3600000, false, issues);
    }
    for (const auto& instance : validateFamily("pdr.gpio", false, 0, "gpio"))
    {
        validateId(instance, "pdr.gpio");
        if (!instance.enabled) continue;
        integerRange(config, instance.prefix + ".pin", 0, 1000000, true, issues);
        integerRange(config, instance.prefix + ".exportTimeoutMilliseconds", 0, 60000, false, issues);
        const auto direction = config.getString(instance.prefix + ".direction", "in");
        if (direction != "in" && direction != "out")
            issues.push_back({instance.prefix + ".direction", "must be in or out"});
    }
    for (const auto& instance : validateFamily("pdr.xbee", false, 0, "xbee-sensor"))
    {
        validateId(instance, "pdr.xbee");
        if (!instance.enabled) continue;
        const auto transport = config.getString(instance.prefix + ".transport", "port");
        allowedString(config, instance.prefix + ".transport", {"port", "loopback"}, issues);
        if (transport == "port") requireString(config, instance.prefix + ".port", issues);
        requireString(config, instance.prefix + ".sourceAddress", issues);
        if (config.hasProperty(instance.prefix + ".sourceAddress"))
        {
            const auto address = config.getString(instance.prefix + ".sourceAddress");
            try
            {
                std::size_t parsed = 0;
                (void) std::stoull(address, &parsed, 16);
                if (parsed != address.size()) throw std::invalid_argument("trailing characters");
            }
            catch (...)
            {
                issues.push_back({instance.prefix + ".sourceAddress",
                                  "must be a 64-bit hexadecimal address"});
            }
        }
        integerRange(config, instance.prefix + ".baudRate", 1, 4000000, false, issues);
        integerRange(config, instance.prefix + ".analogChannel", 0, 15, false, issues);
        integerRange(config, instance.prefix + ".reconnectDelayMilliseconds", 0, 60000, false, issues);
        integerRange(config, instance.prefix + ".receiveTimeoutMilliseconds", 1, 60000, false, issues);
        integerRange(config, instance.prefix + ".staleAfterMilliseconds", 1, 3600000, false, issues);
        const auto conversion = config.getString(instance.prefix + ".conversion", "raw");
        if (conversion != "raw" && conversion != "millivolts" &&
            conversion != "temperature" && conversion != "humidity")
            issues.push_back({instance.prefix + ".conversion", "unsupported conversion"});
    }
    for (const auto& instance : validateFamily("pdr.can", false, 0, "can-sensor"))
    {
        validateId(instance, "pdr.can");
        if (!instance.enabled) continue;
        const auto transport = config.getString(instance.prefix + ".transport", "socketcan");
        allowedString(config, instance.prefix + ".transport", {"socketcan", "loopback"}, issues);
        if (transport == "socketcan")
            requireString(config, instance.prefix + ".interface", issues);
        integerRange(config, instance.prefix + ".bitOffset", 0, 511, false, issues);
        integerRange(config, instance.prefix + ".bitLength", 1, 64, false, issues);
        int bitOffset = 0;
        int bitLength = 1;
        Poco::NumberParser::tryParse(
            config.getString(instance.prefix + ".bitOffset", "0"), bitOffset);
        Poco::NumberParser::tryParse(
            config.getString(instance.prefix + ".bitLength", "1"), bitLength);
        if (bitOffset + bitLength > 512)
            issues.push_back({instance.prefix + ".bitLength", "signal exceeds 64-byte CAN FD payload"});
        const auto frameIdText = config.getString(instance.prefix + ".frameId", "0");
        try
        {
            std::size_t parsed = 0;
            const auto frameId = std::stoull(frameIdText, &parsed, 0);
            if (parsed != frameIdText.size() || frameId > 0x1FFFFFFFULL)
                throw std::out_of_range("CAN identifier");
            if (!config.getBool(instance.prefix + ".extended", false) && frameId > 0x7FFULL)
                throw std::out_of_range("standard CAN identifier");
        }
        catch (...)
        {
            issues.push_back({instance.prefix + ".frameId", "must be a valid 11-bit or 29-bit CAN identifier"});
        }
        const auto order = config.getString(instance.prefix + ".bitOrder", "little");
        if (order != "little" && order != "big")
            issues.push_back({instance.prefix + ".bitOrder", "must be little or big"});
        integerRange(config, instance.prefix + ".reconnectDelayMilliseconds", 0, 60000, false, issues);
        integerRange(config, instance.prefix + ".receiveTimeoutMilliseconds", 1, 60000, false, issues);
        integerRange(config, instance.prefix + ".staleAfterMilliseconds", 1, 60000, false, issues);
    }
    for (const auto& instance : validateFamily("pdr.led", false, 0, "led"))
    {
        validateId(instance, "pdr.led");
        if (instance.enabled)
            requireString(config, instance.prefix + ".path", issues);
    }
    std::unordered_set<std::string> protocolIds;
    const auto validateProtocolId = [&](const IndexedInstance& instance) {
        if (!instance.enabled) return;
        if (instance.id.empty())
            issues.push_back({instance.prefix + ".id", "required non-empty string"});
        else if (!protocolIds.insert(instance.id).second)
            issues.push_back({instance.prefix + ".id", "duplicate protocol id " + instance.id});
    };
    const auto validateProtocolRecovery = [&](const IndexedInstance& instance) {
        const auto delayKey = instance.prefix + ".reconnectDelayMilliseconds";
        const auto maximumKey = instance.prefix + ".reconnectMaximumDelayMilliseconds";
        integerRange(config, delayKey, 100, 3600000, false, issues);
        integerRange(config, maximumKey, 100, 3600000, false, issues);
        int delay = 1000;
        int maximum = 30000;
        const bool delayValid = Poco::NumberParser::tryParse(
            config.getString(delayKey, "1000"), delay);
        const bool maximumValid = Poco::NumberParser::tryParse(
            config.getString(maximumKey, "30000"), maximum);
        if (delayValid && maximumValid && maximum < delay)
            issues.push_back({maximumKey, "must be greater than or equal to reconnect delay"});
    };
    for (const auto& instance : validateFamily("pdr.mqtt", false, 0, "mqtt"))
    {
        validateProtocolId(instance);
        if (!instance.enabled) continue;
        requireString(config, instance.prefix + ".serverUri", issues);
        const auto serverUri = config.getString(instance.prefix + ".serverUri", "");
        const auto validateEnvironmentBacked = [&](const char* name) {
            const std::string directKey = instance.prefix + "." + name;
            const std::string environmentKey = directKey + "Environment";
            const std::string direct = config.getString(directKey, "");
            const std::string variable = config.getString(environmentKey, "");
            if (!direct.empty() && !variable.empty())
                issues.push_back({environmentKey,
                                  "mutually exclusive with " + directKey});
            if (!variable.empty())
            {
                if (!std::regex_match(variable, std::regex("[A-Za-z_][A-Za-z0-9_]*")))
                    issues.push_back({environmentKey,
                                      "must be a valid environment variable name"});
                else if (!Poco::Environment::has(variable) ||
                         Poco::Environment::get(variable).empty())
                    issues.push_back({environmentKey,
                                      "environment variable is not set or empty: " + variable});
            }
        };
        validateEnvironmentBacked("username");
        validateEnvironmentBacked("password");
        validateEnvironmentBacked("privateKeyPassword");
        const bool tls = serverUri.rfind("ssl://", 0) == 0 ||
                         serverUri.rfind("wss://", 0) == 0;
        const bool hasTlsMaterial =
            !config.getString(instance.prefix + ".trustStore", "").empty() ||
            !config.getString(instance.prefix + ".keyStore", "").empty() ||
            !config.getString(instance.prefix + ".privateKey", "").empty() ||
            !config.getString(instance.prefix + ".privateKeyPassword", "").empty() ||
            !config.getString(instance.prefix + ".enabledCipherSuites", "").empty();
        if (hasTlsMaterial && !tls)
            issues.push_back({instance.prefix + ".serverUri",
                              "TLS material requires ssl:// or wss://"});
        if (!config.getString(instance.prefix + ".privateKey", "").empty() &&
            config.getString(instance.prefix + ".keyStore", "").empty())
            issues.push_back({instance.prefix + ".keyStore",
                              "required when privateKey is configured"});
        if (!config.getString(instance.prefix + ".privateKeyPassword", "").empty() &&
            config.getString(instance.prefix + ".privateKey", "").empty())
            issues.push_back({instance.prefix + ".privateKey",
                              "required when privateKeyPassword is configured"});
        if (tls && config.getString("security.profile", "development") == "production")
        {
            if (!config.getBool(instance.prefix + ".verifyServerCertificate", true))
                issues.push_back({instance.prefix + ".verifyServerCertificate",
                                  "must be true in production"});
            if (!config.getBool(instance.prefix + ".verifyHostname", true))
                issues.push_back({instance.prefix + ".verifyHostname",
                                  "must be true in production"});
        }
        integerRange(config, instance.prefix + ".keepAliveSeconds", 0, 86400, false, issues);
        integerRange(config, instance.prefix + ".connectTimeoutSeconds", 1, 3600, false, issues);
        validateProtocolRecovery(instance);
    }
    for (const auto& instance : validateFamily("pdr.ros", false, 0, "ros"))
    {
        validateProtocolId(instance);
        if (!instance.enabled) continue;
        requireString(config, instance.prefix + ".uri", issues);
        const auto uri = config.getString(instance.prefix + ".uri", "");
        const bool ws = uri.rfind("ws://", 0) == 0;
        const bool wss = uri.rfind("wss://", 0) == 0;
        if (!uri.empty() && !ws && !wss)
            issues.push_back({instance.prefix + ".uri", "scheme must be ws or wss"});
        const std::string authorizationKey = instance.prefix + ".authorization";
        const std::string authorizationEnvironmentKey =
            instance.prefix + ".authorizationEnvironment";
        const std::string authorization = config.getString(authorizationKey, "");
        const std::string authorizationVariable =
            config.getString(authorizationEnvironmentKey, "");
        if (!authorization.empty() && !authorizationVariable.empty())
            issues.push_back({authorizationEnvironmentKey,
                              "mutually exclusive with " + authorizationKey});
        if (!authorizationVariable.empty())
        {
            if (!std::regex_match(authorizationVariable,
                                  std::regex("[A-Za-z_][A-Za-z0-9_]*")))
                issues.push_back({authorizationEnvironmentKey,
                                  "must be a valid environment variable name"});
            else if (!Poco::Environment::has(authorizationVariable) ||
                     Poco::Environment::get(authorizationVariable).empty())
                issues.push_back({authorizationEnvironmentKey,
                                  "environment variable is not set or empty: " +
                                      authorizationVariable});
        }
        const bool hasTlsMaterial =
            !config.getString(instance.prefix + ".trustStore", "").empty() ||
            !config.getString(instance.prefix + ".clientCertificate", "").empty() ||
            !config.getString(instance.prefix + ".privateKey", "").empty();
        if (hasTlsMaterial && !wss)
            issues.push_back({instance.prefix + ".uri", "TLS material requires wss://"});
        const bool hasClientCertificate =
            !config.getString(instance.prefix + ".clientCertificate", "").empty();
        const bool hasPrivateKey =
            !config.getString(instance.prefix + ".privateKey", "").empty();
        if (hasClientCertificate != hasPrivateKey)
            issues.push_back({instance.prefix + ".clientCertificate",
                              "client certificate and private key must be configured together"});
        integerRange(config, instance.prefix + ".maximumMessageSize", 1, 2147483647,
                     false, issues);
        integerRange(config, instance.prefix + ".connectTimeoutSeconds", 1, 3600,
                     false, issues);
        if (wss && config.getString("security.profile", "development") == "production")
        {
            if (!config.getBool(instance.prefix + ".verifyServerCertificate", true))
                issues.push_back({instance.prefix + ".verifyServerCertificate",
                                  "must be true in production"});
            if (!config.getBool(instance.prefix + ".verifyHostname", true))
                issues.push_back({instance.prefix + ".verifyHostname",
                                  "must be true in production"});
        }
        validateProtocolRecovery(instance);
    }
    for (const auto& instance : validateFamily("pdr.udp", false, 0, "udp"))
    {
        validateProtocolId(instance);
        if (!instance.enabled) continue;
        requireString(config, instance.prefix + ".localHost", issues);
        requireString(config, instance.prefix + ".remoteHost", issues);
        integerRange(config, instance.prefix + ".localPort", 0, 65535, false, issues);
        integerRange(config, instance.prefix + ".remotePort", 1, 65535, false, issues);
        validateProtocolRecovery(instance);
    }
    const std::string securityProfile = config.getString("security.profile", "development");
    if (securityProfile != "development" && securityProfile != "production")
    {
        issues.push_back({"security.profile", "must be development or production"});
    }
    else if (securityProfile == "development")
    {
        const std::string host = config.getString("osp.web.server.host", "");
        const bool authenticated = !config.getString("osp.web.authServiceName", "").empty();
        const int securePort = config.getInt("osp.web.server.securePort", 0);
        if (!isLoopbackHost(host) && (!authenticated || securePort <= 0))
            issues.push_back({"security.profile",
                              "development WebUI may bind externally only with authentication and TLS"});
    }
    else
    {
        if (!managementAuthenticationRequired)
            issues.push_back({"pdr.management.authentication.required",
                              "production requires authenticated management operations"});
        if (!managementRequestIdRequired)
            issues.push_back({"pdr.management.idempotency.requireRequestId",
                              "production requires idempotent management request IDs"});
        if (config.getInt("osp.web.server.securePort", 0) <= 0)
            issues.push_back({"osp.web.server.securePort", "production requires TLS"});
        if (config.getString("osp.web.authServiceName", "").empty())
            issues.push_back({"osp.web.authServiceName", "production requires authentication"});
        if (config.getBool("auth.simple.enable", false))
            issues.push_back({"auth.simple.enable",
                              "legacy SimpleAuth is prohibited in production"});
    }
    return issues;
}

void ConfigurationValidator::validateOrThrow(
    const Poco::Util::AbstractConfiguration& config) const
{
    const auto issues = validate(config);
    if (issues.empty())
        return;
    std::ostringstream message;
    message << "configuration validation failed:";
    for (const auto& issue : issues)
        message << " [" << issue.key << ": " << issue.message << ']';
    throw Poco::InvalidArgumentException(message.str());
}
}
