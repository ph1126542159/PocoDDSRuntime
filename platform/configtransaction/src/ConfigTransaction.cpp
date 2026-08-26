#include "PocoDDS/ConfigTransaction/ConfigTransaction.h"

#include <Poco/DigestEngine.h>
#include <Poco/Exception.h>
#include <Poco/SHA2Engine.h>

#include <algorithm>
#include <cctype>
#include <regex>
#include <sstream>

namespace PocoDDS::ConfigTransaction
{
const char* statusName(Status status) noexcept
{
    switch (status)
    {
    case Status::preflighting: return "preflighting";
    case Status::preflightFailed: return "preflight-failed";
    case Status::committing: return "committing";
    case Status::rollingBack: return "rolling-back";
    case Status::rolledBack: return "rolled-back";
    case Status::rollbackFailed: return "rollback-failed";
    case Status::committed: return "committed";
    case Status::recoveryPending: return "recovery-pending";
    }
    return "unknown";
}

Status parseStatus(const std::string& value)
{
    if (value == "preflighting") return Status::preflighting;
    if (value == "preflight-failed") return Status::preflightFailed;
    if (value == "committing") return Status::committing;
    if (value == "rolling-back") return Status::rollingBack;
    if (value == "rolled-back") return Status::rolledBack;
    if (value == "rollback-failed") return Status::rollbackFailed;
    if (value == "committed") return Status::committed;
    if (value == "recovery-pending") return Status::recoveryPending;
    throw Poco::DataFormatException("Unknown configuration transaction status", value);
}

std::string snapshotDigest(const Values& values)
{
    Poco::SHA2Engine engine(Poco::SHA2Engine::SHA_256);
    for (const auto& [key, value] : values)
    {
        engine.update(key);
        const char separator = '\0';
        engine.update(&separator, 1);
        engine.update(value);
        engine.update(&separator, 1);
    }
    return Poco::DigestEngine::digestToHex(engine.digest());
}

bool sensitiveKey(const std::string& key)
{
    std::string lowered(key);
    std::transform(lowered.begin(), lowered.end(), lowered.begin(),
                   [](unsigned char value) { return static_cast<char>(std::tolower(value)); });
    return lowered.find("password") != std::string::npos ||
           lowered.find("secret") != std::string::npos ||
           lowered.find("token") != std::string::npos ||
           lowered.find("privatekey") != std::string::npos;
}

bool environmentReference(const std::string& value)
{
    static const std::regex pattern(R"(^env://[A-Za-z_][A-Za-z0-9_]*$)");
    return value.empty() || std::regex_match(value, pattern);
}

bool sensitiveValueAllowed(const std::string& key, const std::string& value)
{
    if (environmentReference(value)) return true;
    std::string lowered(key);
    std::transform(lowered.begin(), lowered.end(), lowered.begin(),
                   [](unsigned char character) {
                       return static_cast<char>(std::tolower(character));
                   });
    static const std::string suffix = "environment";
    if (lowered.size() < suffix.size() ||
        lowered.compare(lowered.size() - suffix.size(), suffix.size(), suffix) != 0)
        return false;
    static const std::regex variable(R"(^[A-Za-z_][A-Za-z0-9_]*$)");
    return std::regex_match(value, variable);
}

TransactionSummary summarize(const TransactionRecord& record)
{
    return {record.id,
            record.requestId,
            record.principal,
            record.status,
            record.previous.generation,
            record.candidate.generation,
            record.candidate.digest,
            record.changedKeys,
            record.participants,
            record.errorCode,
            record.errorMessage,
            record.createdMicroseconds,
            record.updatedMicroseconds};
}
} // namespace PocoDDS::ConfigTransaction
