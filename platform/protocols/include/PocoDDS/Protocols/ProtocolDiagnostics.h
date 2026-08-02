#pragma once

#include "PocoDDS/Protocols/Protocol.h"
#include "PocoDDS/Reliability/Reliability.h"

#include <cstdint>
#include <string>
#include <utility>

namespace PocoDDS::Protocols
{
struct ProtocolDiagnostics
{
    std::uint64_t successfulOperations{0};
    std::uint64_t failedOperations{0};
    std::uint64_t reconnectAttempts{0};
    std::uint64_t sentMessages{0};
    std::uint64_t receivedMessages{0};
    std::uint64_t sentBytes{0};
    std::uint64_t receivedBytes{0};
    std::uint64_t timeouts{0};
    std::uint64_t handlerFailures{0};
    std::string lastError;
};

inline void resolveFailure(ProtocolDiagnostics& diagnostics,
                           PocoDDS::Reliability::Failure& failure) noexcept
{
    diagnostics.lastError.clear();
    PocoDDS::Reliability::resolve(failure);
}

inline void recordFailure(ProtocolDiagnostics& diagnostics,
                          PocoDDS::Reliability::Failure& failure,
                          std::string code, PocoDDS::Reliability::FailureKind kind,
                          bool retryable, std::string message)
{
    diagnostics.lastError = message;
    failure = PocoDDS::Reliability::makeFailure(
        std::move(code), kind, retryable, std::move(message));
}

class DiagnosticProtocol : public Protocol
{
public:
    virtual ProtocolDiagnostics diagnostics() const = 0;
};

// Optional extension kept separate to preserve DiagnosticProtocol's ABI.
class FailureDiagnosticProtocol
{
public:
    virtual ~FailureDiagnosticProtocol() = default;
    virtual PocoDDS::Reliability::Failure failure() const = 0;
};
}
