#include "InvocationTraceAdapter.h"

#include <stdexcept>
#include <utility>

namespace PocoDDS::ServiceClient
{
namespace
{
constexpr const char* OWNER = "pdr.service.serviceClientRuntime";
}

InvocationTraceAdapter::InvocationTraceAdapter(std::size_t maximumActive)
    : _tracer(OWNER, [] {
          Observability::BusinessTracerOptions options;
          options.bundleName = OWNER;
          return options;
      }()),
      _maximumActive(maximumActive)
{
    if (_maximumActive == 0 || _maximumActive > 100000)
        throw std::invalid_argument(
            "Service Client audit active trace capacity is invalid");
}

void InvocationTraceAdapter::publish(const InvocationAuditEvent& event)
{
    std::lock_guard<std::mutex> lock(_mutex);
    auto found = _spans.find(event.invocationId);
    if (found == _spans.end())
    {
        if (_spans.size() >= _maximumActive)
            throw std::runtime_error(
                "Service Client invocation trace capacity is exhausted");
        Observability::Fields inputs{
            {"invocation.id", event.invocationId},
            {"work.id", event.workId},
            {"principal", event.principal},
            {"target.service", event.serviceName},
            {"target.operation", event.operation}};
        auto span = _tracer.startBusiness(
            "runtime.service-invocation", inputs, event.invocationId);
        found = _spans.emplace(event.invocationId, std::move(span)).first;
    }

    Observability::Fields fields{
        {"event.sequence", std::to_string(event.sequence)},
        {"event.stage", toString(event.stage)},
        {"event.code", event.code},
        {"attempt", std::to_string(event.attempt)},
        {"instance.id", event.instanceId},
        {"runtime.id", event.runtimeId},
        {"runtime.incarnation", std::to_string(event.runtimeIncarnation)},
        {"policy.generation", std::to_string(event.policyGeneration)}};
    found->second.log(toString(event.stage),
                      terminalFailure(event) ? "error" : "info", fields);

    if (!terminal(event)) return;
    if (event.stage == InvocationAuditStage::completed &&
        event.detail == "succeeded")
        found->second.success({{"result.code", event.code}});
    else
        found->second.failure(
            event.code.empty() ? toString(event.stage) : event.code,
            event.detail.empty() ? toString(event.stage) : event.detail);
    _spans.erase(found);
}

std::size_t InvocationTraceAdapter::activeTraces() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _spans.size();
}

bool InvocationTraceAdapter::terminal(const InvocationAuditEvent& event)
{
    return event.stage == InvocationAuditStage::validationRejected ||
        event.stage == InvocationAuditStage::authorizationDenied ||
        event.stage == InvocationAuditStage::authorizationError ||
        event.stage == InvocationAuditStage::idempotencyConflict ||
        (event.stage == InvocationAuditStage::idempotencyError &&
         event.detail == "rejected") ||
        event.stage == InvocationAuditStage::admissionRejected ||
        event.stage == InvocationAuditStage::completed;
}

bool InvocationTraceAdapter::terminalFailure(
    const InvocationAuditEvent& event)
{
    return terminal(event) &&
        !(event.stage == InvocationAuditStage::completed &&
          event.detail == "succeeded");
}
} // namespace PocoDDS::ServiceClient
