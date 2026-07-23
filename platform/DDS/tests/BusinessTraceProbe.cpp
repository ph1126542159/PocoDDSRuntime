#include "PocoDDS/DDS/Runtime.h"

#include "PocoDDS/Observability/BusinessTracer.h"
#include "PocoDDS/Observability/TraceSerialization.h"

#include <chrono>
#include <iostream>
#include <optional>
#include <thread>

int main()
{
    using PocoDDS::FastDDS::Envelope;
    using PocoDDS::FastDDS::Runtime;
    using PocoDDS::Observability::BusinessTracer;
    using PocoDDS::Observability::BusinessTracerOptions;

    try
    {
        Runtime runtime(0, "pdr-business-trace-probe");
        runtime.start();
        runtime.preparePublisher("pdr.observability.span");
        std::optional<PocoDDS::Observability::SpanSnapshot> latest;
        BusinessTracerOptions options;
        options.bundleName = "probe.bundle";
        options.onChanged = [&](const auto& snapshot) {
            latest = snapshot;
            Envelope envelope;
            envelope.kind = "observability.span";
            envelope.operation = "upsert";
            envelope.payload =
                PocoDDS::Observability::serializeSpanSnapshot(snapshot);
            envelope.traceParent = snapshot.traceParent;
            envelope.businessName = snapshot.businessName;
            envelope.businessInstanceId = snapshot.businessInstanceId;
            runtime.publish("pdr.observability.span", envelope);
        };
        BusinessTracer tracer("probe.remote-service", std::move(options));
        std::this_thread::sleep_for(std::chrono::seconds(2));
        auto business = tracer.startBusiness(
            "跨进程业务验收", {{"requestId", "MULTIPROCESS-1"}}, "multiprocess-acceptance-1");
        {
            auto step = business.startStep("远程参数校验", {{"value", "42"}});
            step.log("remote validation passed");
            step.success({{"normalized", "42"}});
        }
        {
            auto step = business.startStep("远程业务处理");
            step.success({{"result", "accepted"}});
        }
        business.success({{"final", "done"}});
        if (!latest)
            throw std::runtime_error("business tracer did not produce a snapshot");
        Envelope finalEnvelope;
        finalEnvelope.kind = "observability.span";
        finalEnvelope.operation = "upsert";
        finalEnvelope.payload =
            PocoDDS::Observability::serializeSpanSnapshot(*latest);
        for (int attempt = 0; attempt < 5; ++attempt)
        {
            runtime.publish("pdr.observability.span", finalEnvelope);
            std::this_thread::sleep_for(std::chrono::milliseconds(250));
        }
        runtime.stop();
        std::cout << "BUSINESS_TRACE_PROBE_PASS\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "BUSINESS_TRACE_PROBE_FAIL " << exception.what() << '\n';
        return 1;
    }
}
