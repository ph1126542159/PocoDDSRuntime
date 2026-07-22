#include "PocoDDS/Observability/BusinessTracer.h"

#include <opentelemetry/context/context.h>
#include <opentelemetry/context/propagation/text_map_propagator.h>
#include <opentelemetry/exporters/memory/in_memory_span_exporter.h>
#include <opentelemetry/sdk/resource/resource.h>
#include <opentelemetry/sdk/trace/simple_processor_factory.h>
#include <opentelemetry/sdk/trace/tracer_provider_factory.h>
#include <opentelemetry/trace/propagation/http_trace_context.h>
#include <opentelemetry/trace/provider.h>

#include <utility>

#if defined(PDR_ENABLE_OTLP_HTTP)
#include "OtlpHttpJsonExporter.h"
#endif

namespace PocoDDS::Observability
{
namespace
{
namespace otel = opentelemetry;

class TraceCarrier : public otel::context::propagation::TextMapCarrier
{
  public:
    explicit TraceCarrier(std::string value = {}) : _value(std::move(value)) {}

    otel::nostd::string_view Get(otel::nostd::string_view key) const noexcept override
    {
        if (key == "traceparent")
            return _value;
        return {};
    }

    void Set(otel::nostd::string_view key, otel::nostd::string_view value) noexcept override
    {
        if (key == "traceparent")
            _value.assign(value.data(), value.size());
    }

    const std::string& value() const { return _value; }

  private:
    std::string _value;
};

std::string toHex(const otel::trace::TraceId& id)
{
    char value[otel::trace::TraceId::kSize * 2];
    id.ToLowerBase16({value, sizeof(value)});
    return {value, sizeof(value)};
}

std::string toHex(const otel::trace::SpanId& id)
{
    char value[otel::trace::SpanId::kSize * 2];
    id.ToLowerBase16({value, sizeof(value)});
    return {value, sizeof(value)};
}
} // namespace

class BusinessTracer::Impl
{
  public:
    Impl(const std::string& serviceName, const BusinessTracerOptions& options)
    {
        auto exporter = std::make_unique<otel::exporter::memory::InMemorySpanExporter>();
        data = exporter->GetData();
        std::vector<std::unique_ptr<otel::sdk::trace::SpanProcessor>> processors;
        processors.push_back(
            otel::sdk::trace::SimpleSpanProcessorFactory::Create(std::move(exporter)));
#if defined(PDR_ENABLE_OTLP_HTTP)
        if (!options.otlpHttpEndpoint.empty())
            processors.push_back(otel::sdk::trace::SimpleSpanProcessorFactory::Create(
                createOtlpHttpJsonExporter(options.otlpHttpEndpoint, options.otlpHeaders)));
#else
        if (!options.otlpHttpEndpoint.empty())
            throw std::invalid_argument("OTLP/HTTP support was not enabled at build time");
#endif
        auto resource = otel::sdk::resource::Resource::Create({{"service.name", serviceName}});
        provider = otel::sdk::trace::TracerProviderFactory::Create(std::move(processors), resource);
        tracer = provider->GetTracer(serviceName, "1.0.0");
    }

    std::shared_ptr<otel::exporter::memory::InMemorySpanData> data;
    std::shared_ptr<otel::trace::TracerProvider> provider;
    otel::nostd::shared_ptr<otel::trace::Tracer> tracer;
};

class BusinessSpan::Impl
{
  public:
    std::shared_ptr<BusinessTracer::Impl> owner;
    otel::nostd::shared_ptr<otel::trace::Span> span;
    bool finished = false;
};

BusinessSpan::BusinessSpan() = default;
BusinessSpan::BusinessSpan(std::unique_ptr<Impl> impl) : _impl(std::move(impl)) {}
BusinessSpan::BusinessSpan(BusinessSpan&& other) noexcept = default;
BusinessSpan& BusinessSpan::operator=(BusinessSpan&& other) noexcept = default;

BusinessSpan::~BusinessSpan()
{
    if (_impl && !_impl->finished)
        finish("cancelled");
}

std::string BusinessSpan::traceParent() const
{
    if (!_impl || !_impl->span)
        return {};
    TraceCarrier carrier;
    otel::context::Context context;
    context = otel::trace::SetSpan(context, _impl->span);
    otel::trace::propagation::HttpTraceContext().Inject(carrier, context);
    return carrier.value();
}

void BusinessSpan::addLog(const std::string& message)
{
    if (_impl && !_impl->finished)
        _impl->span->AddEvent("log", {{"log.message", message}});
}

void BusinessSpan::finish(const std::string& status,
                          const std::map<std::string, std::string>& outputs)
{
    if (!_impl || _impl->finished)
        return;
    for (const auto& output : outputs)
        _impl->span->SetAttribute("business.output." + output.first, output.second);
    _impl->span->SetAttribute("business.status", status);
    _impl->span->SetStatus(status == "success" ? otel::trace::StatusCode::kOk
                                               : otel::trace::StatusCode::kError,
                           status);
    _impl->span->End();
    _impl->finished = true;
}

BusinessTracer::BusinessTracer(std::string serviceName) : BusinessTracer(std::move(serviceName), {})
{
}

BusinessTracer::BusinessTracer(std::string serviceName, BusinessTracerOptions options)
    : _impl(std::make_shared<Impl>(serviceName, options))
{
}

BusinessTracer::~BusinessTracer() = default;

BusinessSpan BusinessTracer::start(const std::string& operation,
                                   const std::map<std::string, std::string>& inputs,
                                   const std::string& parentTraceParent)
{
    otel::trace::StartSpanOptions options;
    if (!parentTraceParent.empty())
    {
        TraceCarrier carrier(parentTraceParent);
        otel::context::Context context;
        auto extracted = otel::trace::propagation::HttpTraceContext().Extract(carrier, context);
        options.parent = otel::trace::GetSpan(extracted)->GetContext();
    }
    auto span = _impl->tracer->StartSpan(operation, options);
    for (const auto& input : inputs)
        span->SetAttribute("business.input." + input.first, input.second);
    auto impl = std::make_unique<BusinessSpan::Impl>();
    impl->owner = _impl;
    impl->span = std::move(span);
    return BusinessSpan(std::move(impl));
}

std::vector<CompletedSpan> BusinessTracer::drain()
{
    std::vector<CompletedSpan> result;
    for (auto& span : _impl->data->GetSpans())
    {
        CompletedSpan completed;
        completed.name = std::string(span->GetName());
        completed.traceId = toHex(span->GetTraceId());
        completed.spanId = toHex(span->GetSpanId());
        if (span->GetParentSpanId().IsValid())
            completed.parentSpanId = toHex(span->GetParentSpanId());
        completed.status = std::string(span->GetDescription());
        completed.durationNanoseconds = span->GetDuration().count();
        result.push_back(std::move(completed));
    }
    return result;
}

} // namespace PocoDDS::Observability
