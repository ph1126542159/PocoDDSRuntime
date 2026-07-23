#include "PocoDDS/Observability/BusinessTracer.h"
#include "PocoDDS/Observability/TraceStore.h"

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
