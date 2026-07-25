#include "PocoDDS/Configuration/ConfigurationValidator.h"

#include "Poco/Exception.h"
#include "Poco/NumberParser.h"
#include "Poco/Util/AbstractConfiguration.h"

#include <sstream>

namespace PocoDDS::Configuration
{
namespace
{
void requireString(const Poco::Util::AbstractConfiguration& config,
                   const char* key,
                   std::vector<ValidationIssue>& issues)
{
    if (!config.hasProperty(key) || config.getString(key, "").empty())
        issues.push_back({key, "required non-empty string"});
}

void integerRange(const Poco::Util::AbstractConfiguration& config,
                  const char* key,
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
    integerRange(config, "pdr.modbus.port", 1, 65535, false, issues);
    integerRange(config, "pdr.modbus.unitId", 0, 247, false, issues);
    integerRange(config, "pdr.serial.baudRate", 1, 4000000, false, issues);
    integerRange(config, "pdr.gnss.baudRate", 1, 4000000, false, issues);
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
