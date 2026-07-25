#pragma once

#include <string>
#include <vector>

namespace Poco::Util
{
class AbstractConfiguration;
}

namespace PocoDDS::Configuration
{
struct ValidationIssue
{
    std::string key;
    std::string message;
};

class ConfigurationValidator
{
public:
    [[nodiscard]] std::vector<ValidationIssue> validate(
        const Poco::Util::AbstractConfiguration& configuration) const;
    void validateOrThrow(const Poco::Util::AbstractConfiguration& configuration) const;
};
}
