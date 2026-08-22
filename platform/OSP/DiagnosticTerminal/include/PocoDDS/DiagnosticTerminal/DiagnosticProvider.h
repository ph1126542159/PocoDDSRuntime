#pragma once

#include "Poco/OSP/Service.h"

#include <cstdint>
#include <functional>
#include <map>
#include <string>
#include <typeinfo>
#include <utility>
#include <vector>

namespace PocoDDS::DiagnosticTerminal
{
enum class Severity
{
    info,
    warning,
    error,
    critical
};

struct Evidence
{
    std::string source;
    std::string message;
    std::map<std::string, std::string> attributes;
};

struct Finding
{
    std::string code;
    Severity severity{Severity::info};
    std::string scope;
    std::string target;
    std::string summary;
    std::string detail;
    std::string remediation;
    std::string confidence{"high"};
    std::string traceId;
    std::vector<Evidence> evidence;
};

struct Query
{
    std::string scope{"all"};
    std::string target;
    bool deep{false};
    std::int64_t sinceMicroseconds{0};
    std::function<bool()> cancelled;
};

struct Snapshot
{
    std::string provider;
    std::string scope;
    std::string target;
    std::map<std::string, std::string> facts;
    std::vector<Finding> findings;
};

class DiagnosticProvider : public Poco::OSP::Service
{
public:
    static constexpr const char* SERVICE_PROPERTY = "pdr.diagnostics.provider";

    virtual std::string providerId() const = 0;
    virtual std::vector<std::string> scopes() const = 0;
    virtual Snapshot diagnose(const Query& query) const = 0;

    const std::type_info& type() const override { return typeid(DiagnosticProvider); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(DiagnosticProvider).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~DiagnosticProvider() override = default;
};

inline const char* severityName(Severity severity) noexcept
{
    switch (severity)
    {
    case Severity::info: return "INFO";
    case Severity::warning: return "WARN";
    case Severity::error: return "FAIL";
    case Severity::critical: return "CRITICAL";
    }
    return "FAIL";
}
} // namespace PocoDDS::DiagnosticTerminal
