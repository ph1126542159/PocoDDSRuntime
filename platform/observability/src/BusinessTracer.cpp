#include "PocoDDS/Observability/BusinessTracer.h"

#include "OtlpHttpJsonExporter.h"
#include "PocoDDS/Observability/TraceStore.h"

#include <Poco/Environment.h>
#include <Poco/Dynamic/Var.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Process.h>
#include <Poco/Timestamp.h>
#include <Poco/UUIDGenerator.h>

#include <opentelemetry/context/context.h>
#include <opentelemetry/context/propagation/text_map_propagator.h>
#include <opentelemetry/sdk/resource/resource.h>
#include <opentelemetry/sdk/trace/simple_processor_factory.h>
#include <opentelemetry/sdk/trace/tracer_provider_factory.h>
#include <opentelemetry/trace/propagation/http_trace_context.h>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <stdexcept>
#include <sstream>
#include <utility>
#include <vector>

namespace PocoDDS::Observability
{
namespace
{
namespace otel = opentelemetry;

class TraceCarrier final : public otel::context::propagation::TextMapCarrier
{
public:
    explicit TraceCarrier(std::string value = {}) : _value(std::move(value)) {}
    otel::nostd::string_view Get(otel::nostd::string_view key) const noexcept override
    {
        return key == "traceparent" ? otel::nostd::string_view(_value) : otel::nostd::string_view{};
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

template <typename Id> std::string hexId(const Id& id)
{
    char value[Id::kSize * 2];
    id.ToLowerBase16({value, sizeof(value)});
    return {value, sizeof(value)};
}

long long nowMicroseconds()
{
    return Poco::Timestamp().epochMicroseconds();
}

std::string lower(std::string value)
{
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    return value;
}

bool isSensitiveKey(const std::string& key, const DataPolicy& policy)
{
    const auto normalized = lower(key);
    return std::any_of(policy.redactedKeyFragments.begin(), policy.redactedKeyFragments.end(),
                       [&](const auto& fragment) {
                           return normalized.find(lower(fragment)) != normalized.npos;
                       });
}

Poco::Dynamic::Var sanitizeJsonValue(const Poco::Dynamic::Var& source,
                                     const DataPolicy& policy,
                                     unsigned depth)
{
    if (depth > 16)
        return "[MAX_DEPTH]";
    if (source.type() == typeid(Poco::JSON::Object::Ptr))
    {
        auto result = new Poco::JSON::Object;
        const auto object = source.extract<Poco::JSON::Object::Ptr>();
        std::size_t count = 0;
        for (const auto& item : *object)
        {
            if (count++ >= policy.maximumFieldCount)
                break;
            result->set(item.first, isSensitiveKey(item.first, policy)
                                        ? Poco::Dynamic::Var(policy.redactedValue)
                                        : sanitizeJsonValue(item.second, policy, depth + 1));
        }
        return Poco::JSON::Object::Ptr(result);
    }
    if (source.type() == typeid(Poco::JSON::Array::Ptr))
    {
        auto result = new Poco::JSON::Array;
        const auto array = source.extract<Poco::JSON::Array::Ptr>();
        const auto count = std::min<std::size_t>(array->size(), policy.maximumFieldCount);
        for (std::size_t index = 0; index < count; ++index)
            result->add(sanitizeJsonValue(array->get(static_cast<unsigned>(index)), policy,
                                          depth + 1));
        return Poco::JSON::Array::Ptr(result);
    }
    if (source.isString())
    {
        auto value = source.convert<std::string>();
        if (value.size() > policy.maximumValueLength)
            value = value.substr(0, policy.maximumValueLength) + "...[TRUNCATED]";
        return value;
    }
    return source;
}

std::string sanitizeValue(const std::string& value, const DataPolicy& policy)
{
    if (!value.empty() && (value.front() == '{' || value.front() == '['))
    {
        try
        {
            auto sanitized =
                sanitizeJsonValue(Poco::JSON::Parser().parse(value), policy, 0);
            std::ostringstream stream;
            if (sanitized.type() == typeid(Poco::JSON::Object::Ptr))
                sanitized.extract<Poco::JSON::Object::Ptr>()->stringify(stream);
            else
                sanitized.extract<Poco::JSON::Array::Ptr>()->stringify(stream);
            auto result = stream.str();
            if (result.size() > policy.maximumValueLength)
                result = result.substr(0, policy.maximumValueLength) + "...[TRUNCATED]";
            return result;
        }
        catch (...)
        {
            // Preserve non-JSON text below, subject to the same size limit.
        }
    }
    return value.size() > policy.maximumValueLength
               ? value.substr(0, policy.maximumValueLength) + "...[TRUNCATED]"
               : value;
}

Fields sanitize(const Fields& source, const DataPolicy& policy)
{
    Fields result;
    for (const auto& item : source)
    {
        if (result.size() >= policy.maximumFieldCount)
            break;
        if (isSensitiveKey(item.first, policy))
            result[item.first] = policy.redactedValue;
        else
            result[item.first] = sanitizeValue(item.second, policy);
    }
    return result;
}
} // namespace

class BusinessTracer::Impl
{
public:
    Impl(std::string name, BusinessTracerOptions configured)
        : serviceName(std::move(name)), options(std::move(configured))
    {
        std::vector<std::unique_ptr<otel::sdk::trace::SpanProcessor>> processors;
        if (!options.otlpHttpEndpoint.empty())
        {
            processors.push_back(otel::sdk::trace::SimpleSpanProcessorFactory::Create(
                createOtlpHttpJsonExporter(options.otlpHttpEndpoint, options.otlpHeaders)));
        }
        auto resource = otel::sdk::resource::Resource::Create(
            {{"service.name", serviceName},
             {"service.namespace", "PocoDDSRuntime"},
             {"service.instance.id", Poco::Environment::nodeName() + ":" +
                                         std::to_string(Poco::Process::id())}});
        provider = otel::sdk::trace::TracerProviderFactory::Create(std::move(processors), resource);
        tracer = provider->GetTracer("PocoDDS.BusinessTracing", "1.0.0");
    }

    void changed(const SpanSnapshot& snapshot) noexcept
    {
        try
        {
            globalTraceStore().upsert(snapshot);
            if (options.onChanged)
                options.onChanged(snapshot);
        }
        catch (...)
        {
            // Observability must never alter the business result.
        }
    }

    std::string serviceName;
    BusinessTracerOptions options;
    std::shared_ptr<otel::trace::TracerProvider> provider;
    otel::nostd::shared_ptr<otel::trace::Tracer> tracer;
};

class BusinessSpan::Impl
{
public:
    std::shared_ptr<BusinessTracer::Impl> owner;
    otel::nostd::shared_ptr<otel::trace::Span> span;
    SpanSnapshot snapshot;
    std::chrono::steady_clock::time_point started;
    bool ended{false};

    void publish() { owner->changed(snapshot); }
};

namespace
{
std::string injectTraceParent(const otel::nostd::shared_ptr<otel::trace::Span>& span)
{
    TraceCarrier carrier;
    otel::context::Context baseContext;
    auto context = otel::trace::SetSpan(baseContext, span);
    otel::trace::propagation::HttpTraceContext().Inject(carrier, context);
    return carrier.value();
}

std::shared_ptr<BusinessSpan::Impl> createSpan(
    const std::shared_ptr<BusinessTracer::Impl>& owner,
    const std::string& businessName,
    const std::string& operation,
    const Fields& inputs,
    const std::string& parentTraceParent,
    const std::string& businessInstanceId)
{
    otel::trace::StartSpanOptions startOptions;
    if (!parentTraceParent.empty())
    {
        TraceCarrier carrier(parentTraceParent);
        otel::context::Context baseContext;
        const auto extracted = otel::trace::propagation::HttpTraceContext().Extract(
            carrier, baseContext);
        startOptions.parent = otel::trace::GetSpan(extracted)->GetContext();
    }
    auto span = owner->tracer->StartSpan(operation, startOptions);
    const auto safeInputs = sanitize(inputs, owner->options.dataPolicy);
    span->SetAttribute("business.name", businessName);
    span->SetAttribute("business.instance.id", businessInstanceId);
    span->SetAttribute("business.bundle.name", owner->options.bundleName);
    for (const auto& input : safeInputs)
        span->SetAttribute("business.input." + input.first, input.second);

    auto result = std::make_shared<BusinessSpan::Impl>();
    result->owner = owner;
    result->span = std::move(span);
    result->started = std::chrono::steady_clock::now();
    result->snapshot.businessName = businessName;
    result->snapshot.businessInstanceId = businessInstanceId;
    result->snapshot.operation = operation;
    result->snapshot.serviceName = owner->serviceName;
    result->snapshot.bundleName = owner->options.bundleName;
    result->snapshot.hostName = Poco::Environment::nodeName();
    result->snapshot.processId = static_cast<unsigned long>(Poco::Process::id());
    const auto context = result->span->GetContext();
    result->snapshot.traceId = hexId(context.trace_id());
    result->snapshot.spanId = hexId(context.span_id());
    if (!parentTraceParent.empty() && parentTraceParent.size() >= 52)
        result->snapshot.parentSpanId = parentTraceParent.substr(36, 16);
    result->snapshot.traceParent = injectTraceParent(result->span);
    result->snapshot.startedUnixMicroseconds = nowMicroseconds();
    result->snapshot.inputs = safeInputs;
    result->publish();
    return result;
}

void finishSpan(const std::shared_ptr<BusinessSpan::Impl>& impl,
                std::string status,
                const Fields& outputs,
                std::string errorCode,
                std::string errorMessage)
{
    if (!impl || impl->ended)
        return;
    impl->snapshot.outputs = sanitize(outputs, impl->owner->options.dataPolicy);
    impl->snapshot.status = std::move(status);
    impl->snapshot.errorCode = std::move(errorCode);
    impl->snapshot.errorMessage = std::move(errorMessage);
    impl->snapshot.endedUnixMicroseconds = nowMicroseconds();
    impl->snapshot.durationNanoseconds =
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now() - impl->started)
            .count();
    for (const auto& output : impl->snapshot.outputs)
        impl->span->SetAttribute("business.output." + output.first, output.second);
    impl->span->SetAttribute("business.status", impl->snapshot.status);
    if (!impl->snapshot.errorCode.empty())
        impl->span->SetAttribute("error.type", impl->snapshot.errorCode);
    if (!impl->snapshot.errorMessage.empty())
        impl->span->SetAttribute("error.message", impl->snapshot.errorMessage);
    if (impl->snapshot.status == "success")
        impl->span->SetStatus(otel::trace::StatusCode::kOk);
    else
        impl->span->SetStatus(otel::trace::StatusCode::kError, impl->snapshot.errorMessage);
    impl->span->End();
    impl->ended = true;
    impl->publish();
}
} // namespace

BusinessSpan::BusinessSpan() = default;
BusinessSpan::BusinessSpan(std::shared_ptr<Impl> impl) : _impl(std::move(impl)) {}
BusinessSpan::BusinessSpan(BusinessSpan&& other) noexcept = default;
BusinessSpan& BusinessSpan::operator=(BusinessSpan&& other) noexcept = default;
BusinessSpan::~BusinessSpan()
{
    if (_impl && !_impl->ended)
        finishSpan(_impl, "cancelled", {}, "scope_abandoned",
                   "business span left scope without an explicit result");
}

BusinessSpan BusinessSpan::startStep(const std::string& operation, const Fields& inputs)
{
    if (!_impl || _impl->ended)
        throw std::logic_error("cannot start a step from a finished business span");
    return BusinessSpan(createSpan(_impl->owner, _impl->snapshot.businessName, operation, inputs,
                                   _impl->snapshot.traceParent,
                                   _impl->snapshot.businessInstanceId));
}

std::string BusinessSpan::traceParent() const
{
    return _impl ? _impl->snapshot.traceParent : std::string{};
}

std::string BusinessSpan::businessInstanceId() const
{
    return _impl ? _impl->snapshot.businessInstanceId : std::string{};
}

void BusinessSpan::log(const std::string& message,
                       const std::string& level,
                       const Fields& fields)
{
    if (!_impl || _impl->ended)
        return;
    TraceLog record;
    record.timestampUnixMicroseconds = nowMicroseconds();
    record.level = level;
    record.message = message.size() > _impl->owner->options.dataPolicy.maximumValueLength
                         ? message.substr(0, _impl->owner->options.dataPolicy.maximumValueLength) +
                               "...[TRUNCATED]"
                         : message;
    record.fields = sanitize(fields, _impl->owner->options.dataPolicy);
    _impl->snapshot.logs.push_back(record);
    _impl->span->AddEvent("log", {{"log.severity", record.level},
                                  {"log.message", record.message}});
    _impl->publish();
}

void BusinessSpan::success(const Fields& outputs)
{
    finishSpan(_impl, "success", outputs, {}, {});
}

void BusinessSpan::failure(const std::string& errorCode,
                           const std::string& errorMessage,
                           const Fields& outputs)
{
    finishSpan(_impl, "failed", outputs, errorCode, errorMessage);
}

void BusinessSpan::cancel(const std::string& reason)
{
    finishSpan(_impl, "cancelled", {}, "cancelled", reason);
}

bool BusinessSpan::finished() const noexcept
{
    return !_impl || _impl->ended;
}

BusinessTracer::BusinessTracer(std::string serviceName, BusinessTracerOptions options)
    : _impl(std::make_shared<Impl>(std::move(serviceName), std::move(options)))
{
}
BusinessTracer::~BusinessTracer() = default;

BusinessSpan BusinessTracer::startBusiness(const std::string& businessName,
                                           const Fields& inputs,
                                           const std::string& businessInstanceId)
{
    const auto id = businessInstanceId.empty()
                        ? Poco::UUIDGenerator::defaultGenerator().createRandom().toString()
                        : businessInstanceId;
    return startSpan(businessName, businessName, inputs, {}, id);
}

BusinessSpan BusinessTracer::continueBusiness(const std::string& businessName,
                                              const std::string& operation,
                                              const std::string& parentTraceParent,
                                              const std::string& businessInstanceId,
                                              const Fields& inputs)
{
    if (parentTraceParent.empty())
        throw std::invalid_argument("parent traceparent is required");
    return startSpan(businessName, operation, inputs, parentTraceParent, businessInstanceId);
}

BusinessSpan BusinessTracer::startSpan(const std::string& businessName,
                                       const std::string& operation,
                                       const Fields& inputs,
                                       const std::string& parentTraceParent,
                                       const std::string& businessInstanceId)
{
    return BusinessSpan(
        createSpan(_impl, businessName, operation, inputs, parentTraceParent, businessInstanceId));
}
} // namespace PocoDDS::Observability
