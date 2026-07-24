#include "PocoDDS/Observability/BusinessTracer.h"
#include "PocoDDS/Observability/TraceStore.h"

#include <Poco/DirectoryIterator.h>
#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/TemporaryFile.h>
#include <Poco/Timestamp.h>

#include <iostream>
#include <cstdlib>
#include <stdexcept>

namespace
{
void require(bool condition, const char* message)
{
    if (!condition)
        throw std::runtime_error(message);
}

std::string testEndpoint()
{
#if defined(_WIN32)
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, "PDR_TEST_OTLP_ENDPOINT") != 0 || !value)
        return {};
    std::string result(value);
    std::free(value);
    return result;
#else
    const auto* value = std::getenv("PDR_TEST_OTLP_ENDPOINT");
    return value ? value : "";
#endif
}
}

int main()
{
    using namespace PocoDDS::Observability;
    try
    {
        globalTraceStore().clear();
        BusinessTracerOptions options;
        options.bundleName = "order.bundle";
        options.dataPolicy.maximumValueLength = 64;
        options.otlpHttpEndpoint = testEndpoint();
        BusinessTracer tracer("order.service", options);

        auto business = tracer.startBusiness(
            "处理订单",
            {{"orderId", "A-42"},
             {"password", "do-not-store"},
             {"request.payload", R"({"user":"alice","accessToken":"hidden-token"})"}},
            "biz-A-42");
        auto summaries = globalTraceStore().recent();
        require(summaries.size() == 1 && summaries.front().status == "running",
                "running root span was not published");
        auto running = globalTraceStore().trace(summaries.front().traceId);
        require(running.front().inputs.at("password") == "[REDACTED]",
                "sensitive input was not redacted");
        require(running.front().inputs.at("request.payload").find("hidden-token") ==
                    std::string::npos,
                "nested JSON secret was not redacted");

        {
            auto step = business.startStep(
                "查询库存",
                {{"product",
                  "very-long-product-value-that-exceeds-the-configured-sixty-four-byte-limit"}});
            step.log("inventory reserved", "info", {{"warehouse", "north"}});
            step.success({{"available", "12"}});
        }
        {
            auto step = business.startStep("创建支付");
            step.failure("PAYMENT_TIMEOUT", "provider timed out");
        }
        business.failure("BUSINESS_FAILED", "payment failed");

        summaries = globalTraceStore().recent();
        require(summaries.front().status == "failed", "failed status missing");
        const auto nodes = globalTraceStore().trace(summaries.front().traceId);
        require(nodes.size() == 3, "trace graph does not contain all steps");
        require(nodes[1].parentSpanId == nodes[0].spanId, "parent/child relation is invalid");
        require(nodes[1].inputs.at("product").find("[TRUNCATED]") != std::string::npos,
                "long parameter was not truncated");
        require(nodes[1].logs.size() == 1, "correlated step log missing");

        const std::string historyDirectory =
            Poco::TemporaryFile::tempName("pdr-trace-history-");
        pdrConfigureTracePersistence(historyDirectory.c_str(), 10);
        const long long current = Poco::Timestamp().epochMicroseconds();
        SpanSnapshot first;
        first.traceId = "history-trace-current";
        first.spanId = "span-1";
        first.businessName = "历史订单";
        first.businessInstanceId = "history-1";
        first.operation = "写入";
        first.status = "success";
        first.startedUnixMicroseconds = current;
        first.endedUnixMicroseconds = current + 1000;
        first.durationNanoseconds = 1000000;
        globalTraceStore().upsert(first);
        first.status = "failed";
        first.errorCode = "TEST";
        globalTraceStore().upsert(first);

        SpanSnapshot previous = first;
        previous.traceId = "history-trace-previous";
        previous.spanId = "span-2";
        previous.businessInstanceId = "history-2";
        previous.status = "success";
        previous.startedUnixMicroseconds =
            current - 2LL * 60LL * 60LL * 1000000LL;
        globalTraceStore().upsert(previous);

        TraceHistoryQuery query;
        query.fromUnixMicroseconds = current - 3LL * 60LL * 60LL * 1000000LL;
        query.toUnixMicroseconds = current + 1000000;
        query.businessName = "历史";
        query.limit = 10;
        std::vector<TraceSummary> history;
        const auto append = [](void* context, const char* traceId,
                               const char* businessName,
                               const char* businessInstanceId,
                               const char* status,
                               long long startedUnixMicroseconds,
                               long long durationNanoseconds,
                               std::size_t stepCount,
                               const char* failedOperation) {
            auto* records = static_cast<std::vector<TraceSummary>*>(context);
            records->push_back({traceId, businessName, businessInstanceId, status,
                                startedUnixMicroseconds, durationNanoseconds,
                                stepCount, failedOperation});
        };
        const bool hasMore = pdrQueryTraceHistory(
            query.fromUnixMicroseconds, query.toUnixMicroseconds,
            query.businessName.c_str(), query.status.c_str(), query.limit,
            query.offset, append, &history);
        require(!hasMore, "unexpected extra history page");
        require(history.size() == 2, "hourly history shards were not queried");
        require(history.front().traceId == "history-trace-current",
                "history ordering is invalid");
        require(history.front().stepCount == 1,
                "span upsert created a duplicate history step");
        require(Poco::File(Poco::Path(historyDirectory,
                                      "business-traces-catalog.sqlite")).exists(),
                "trace history catalog database missing");
        std::size_t shardCount = 0;
        for (Poco::DirectoryIterator it(historyDirectory), end; it != end; ++it)
            if (it.name().rfind("business-traces-", 0) == 0 &&
                it.name() != "business-traces-catalog.sqlite" &&
                Poco::Path(it.name()).getExtension() == "sqlite")
                ++shardCount;
        require(shardCount == 2, "trace history was not split by hour");
        Poco::File(historyDirectory).remove(true);

        std::cout << "BUSINESS_TRACING_PASS trace=" << summaries.front().traceId
                  << " nodes=" << nodes.size() << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "BUSINESS_TRACING_FAIL " << exception.what() << '\n';
        return 1;
    }
}
