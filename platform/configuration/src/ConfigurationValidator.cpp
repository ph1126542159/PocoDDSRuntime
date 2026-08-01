#include "PocoDDS/Configuration/ConfigurationValidator.h"
#include "PocoDDS/Configuration/IndexedConfiguration.h"

#include "Poco/Exception.h"
#include "Poco/Environment.h"
#include "Poco/NumberParser.h"
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
}

std::vector<ValidationIssue> ConfigurationValidator::validate(
    const Poco::Util::AbstractConfiguration& config) const
{
    std::vector<ValidationIssue> issues;
    requireString(config, "osp.web.server.host", issues);
    integerRange(config, "osp.web.server.port", 1, 65535, true, issues);
    integerRange(config, "pdr.fastdds.domainId", 0, 232, true, issues);
    integerRange(config, "pdr.subprocess.shutdownTimeoutMilliseconds", 1, 3600000, true, issues);
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
