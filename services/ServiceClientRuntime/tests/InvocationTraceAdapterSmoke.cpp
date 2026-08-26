#include "InvocationTraceAdapter.h"

#include "PocoDDS/Observability/TraceStore.h"

#include <algorithm>
#include <atomic>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using namespace PocoDDS::Observability;
using namespace PocoDDS::ServiceClient;

namespace
{
void require(bool condition, const std::string& detail)
{
    if (!condition) throw std::runtime_error(detail);
}

InvocationAuditEvent event(std::string id, std::uint64_t sequence,
                           InvocationAuditStage stage)
{
    InvocationAuditEvent value;
    value.sequence = sequence;
    value.invocationId = std::move(id);
    value.workId = "work-" + value.invocationId;
    value.principal = "orders-reader";
    value.serviceName = "orders.v1";
    value.operation = "read-order";
    value.stage = stage;
    return value;
}
} // namespace

int main()
{
    try
    {
        globalTraceStore().clear();
        InvocationTraceAdapter adapter(32);
        const std::string invocationId = "invocation-trace-success";
        adapter.publish(event(invocationId, 1,
                              InvocationAuditStage::received));
        auto allowed = event(invocationId, 2,
                             InvocationAuditStage::authorizationAllowed);
        allowed.code = "CAPABILITY_ALLOWED";
        allowed.policyGeneration = 7;
        adapter.publish(allowed);
        adapter.publish(event(invocationId, 3,
                              InvocationAuditStage::admitted));
        auto attempt = event(invocationId, 4,
                             InvocationAuditStage::attemptStarted);
        attempt.attempt = 1;
        attempt.instanceId = "orders-a";
        attempt.runtimeId = "runtime-a";
        attempt.runtimeIncarnation = 3;
        adapter.publish(attempt);
        attempt.sequence = 5;
        attempt.stage = InvocationAuditStage::attemptCompleted;
        attempt.code = "ok";
        adapter.publish(attempt);
        auto completed = event(invocationId, 6,
                               InvocationAuditStage::completed);
        completed.code = "succeeded";
        completed.detail = "succeeded";
        adapter.publish(completed);
        require(adapter.activeTraces() == 0,
                "successful invocation trace remained active");

        const auto summaries = globalTraceStore().recent();
        const auto summary = std::find_if(
            summaries.begin(), summaries.end(), [&](const auto& value) {
                return value.businessInstanceId == invocationId;
            });
        require(summary != summaries.end() && summary->status == "success",
                "successful invocation Business Trace is missing");
        const auto spans = globalTraceStore().trace(summary->traceId);
        require(spans.size() == 1 && spans.front().logs.size() == 6 &&
                    spans.front().inputs.at("invocation.id") == invocationId &&
                    spans.front().inputs.count("payload") == 0 &&
                    spans.front().inputs.count("authorization") == 0,
                "invocation trace fields or stage logs are incomplete");

        const std::string deniedId = "invocation-trace-denied";
        adapter.publish(event(deniedId, 7,
                              InvocationAuditStage::received));
        auto denied = event(deniedId, 8,
                            InvocationAuditStage::authorizationDenied);
        denied.code = "CAPABILITY_DEFAULT_DENY";
        denied.detail = "capability decision denied";
        adapter.publish(denied);
        const auto afterDenied = globalTraceStore().recent();
        require(std::any_of(afterDenied.begin(), afterDenied.end(),
                    [&](const auto& value) {
                        return value.businessInstanceId == deniedId &&
                            value.status == "failed";
                    }),
                "authorization denial did not close a failed trace");

        const std::string conflictId = "invocation-trace-conflict";
        adapter.publish(event(conflictId, 9,
                              InvocationAuditStage::received));
        auto conflict = event(conflictId, 10,
                              InvocationAuditStage::idempotencyConflict);
        conflict.code = "SERVICE_CLIENT_IDEMPOTENCY_CONFLICT";
        conflict.detail = "same key was used for a different request";
        adapter.publish(conflict);
        const auto afterConflict = globalTraceStore().recent();
        require(std::any_of(afterConflict.begin(), afterConflict.end(),
                    [&](const auto& value) {
                        return value.businessInstanceId == conflictId &&
                            value.status == "failed";
                    }) && adapter.activeTraces() == 0,
                "idempotency conflict did not close a failed trace");

        std::vector<std::thread> workers;
        std::atomic<std::uint64_t> sequence{100};
        for (int index = 0; index < 8; ++index)
        {
            workers.emplace_back([&, index] {
                const auto id = "concurrent-" + std::to_string(index);
                adapter.publish(event(id, ++sequence,
                                      InvocationAuditStage::received));
                auto done = event(id, ++sequence,
                                  InvocationAuditStage::completed);
                done.code = "succeeded";
                done.detail = "succeeded";
                adapter.publish(done);
            });
        }
        for (auto& worker : workers) worker.join();
        require(adapter.activeTraces() == 0,
                "concurrent invocation traces leaked active state");

        std::cout << "SERVICE_CLIENT_INVOCATION_TRACE_PASS traces="
                  << globalTraceStore().recent().size() << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "SERVICE_CLIENT_INVOCATION_TRACE_ERROR: "
                  << exception.what() << '\n';
        return 1;
    }
}
