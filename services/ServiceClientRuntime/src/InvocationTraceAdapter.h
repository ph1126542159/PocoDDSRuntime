#pragma once

#include "PocoDDS/Observability/BusinessTracer.h"
#include "PocoDDS/ServiceClient/RuntimeCoordinator.h"

#include <cstddef>
#include <map>
#include <mutex>
#include <string>

namespace PocoDDS::ServiceClient
{
class InvocationTraceAdapter
{
public:
    explicit InvocationTraceAdapter(std::size_t maximumActive);

    void publish(const InvocationAuditEvent& event);
    [[nodiscard]] std::size_t activeTraces() const;

private:
    static bool terminal(const InvocationAuditEvent& event);
    static bool terminalFailure(const InvocationAuditEvent& event);

    Observability::BusinessTracer _tracer;
    std::size_t _maximumActive;
    mutable std::mutex _mutex;
    std::map<std::string, Observability::BusinessSpan> _spans;
};
} // namespace PocoDDS::ServiceClient
