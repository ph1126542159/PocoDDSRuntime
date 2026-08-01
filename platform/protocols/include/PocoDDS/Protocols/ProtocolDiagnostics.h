#pragma once

#include "PocoDDS/Protocols/Protocol.h"

#include <cstdint>
#include <string>

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

class DiagnosticProtocol : public Protocol
{
public:
    virtual ProtocolDiagnostics diagnostics() const = 0;
};
}
