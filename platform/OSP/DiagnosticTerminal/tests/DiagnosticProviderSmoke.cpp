#include "PocoDDS/DiagnosticTerminal/DiagnosticProvider.h"

#include <stdexcept>

namespace
{
class ExampleProvider final : public PocoDDS::DiagnosticTerminal::DiagnosticProvider
{
public:
    std::string providerId() const override { return "example"; }
    std::vector<std::string> scopes() const override { return {"bundle", "service"}; }

    PocoDDS::DiagnosticTerminal::Snapshot diagnose(
        const PocoDDS::DiagnosticTerminal::Query& query) const override
    {
        PocoDDS::DiagnosticTerminal::Snapshot result;
        result.provider = providerId();
        result.scope = query.scope;
        result.target = query.target;
        result.facts["deep"] = query.deep ? "true" : "false";
        result.findings.push_back(PocoDDS::DiagnosticTerminal::Finding{
            "PDR-TEST-001",
            PocoDDS::DiagnosticTerminal::Severity::warning,
            "bundle",
            query.target,
            "test finding",
            "test evidence",
            "test remediation"});
        return result;
    }
};

void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}
}

int main()
{
    Poco::AutoPtr<ExampleProvider> provider = new ExampleProvider;
    PocoDDS::DiagnosticTerminal::Query query;
    query.scope = "bundle";
    query.target = "pdr.test";
    query.deep = true;
    const auto snapshot = provider->diagnose(query);
    require(snapshot.provider == "example", "provider id mismatch");
    require(snapshot.scope == "bundle", "scope mismatch");
    require(snapshot.target == "pdr.test", "target mismatch");
    require(snapshot.facts.at("deep") == "true", "deep flag missing");
    require(snapshot.findings.size() == 1, "finding missing");
    require(snapshot.findings.front().code == "PDR-TEST-001", "finding code mismatch");
    require(std::string(PocoDDS::DiagnosticTerminal::severityName(
                PocoDDS::DiagnosticTerminal::Severity::critical)) == "CRITICAL",
            "severity name mismatch");
    return 0;
}
