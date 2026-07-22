#include "OtlpHttpJsonExporter.h"

#include <Poco/Base64Encoder.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/Net/HTTPClientSession.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/StreamCopier.h>
#include <Poco/URI.h>

#include <opentelemetry/nostd/variant.h>
#include <opentelemetry/sdk/trace/span_data.h>

#include <chrono>
#include <cstdint>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <type_traits>
#include <utility>

namespace PocoDDS::Observability
{
namespace
{
namespace otel = opentelemetry;
using Poco::JSON::Array;
using Poco::JSON::Object;

template <typename Id> std::string base64Id(const Id& id)
{
    std::ostringstream output;
    Poco::Base64Encoder encoder(output);
    encoder.rdbuf()->setLineLength(0);
    const auto bytes = id.Id();
    encoder.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    encoder.close();
    return output.str();
}

class AnyValueVisitor
{
  public:
    template <typename Value> Object operator()(const Value& value) const
    {
        Object result;
        if constexpr (std::is_same_v<Value, bool>)
            result.set("boolValue", value);
        else if constexpr (std::is_integral_v<Value>)
            result.set("intValue", std::to_string(value));
        else if constexpr (std::is_floating_point_v<Value>)
            result.set("doubleValue", value);
        else if constexpr (std::is_same_v<Value, std::string>)
            result.set("stringValue", value);
        else
        {
            Array values;
            for (const auto& item : value)
                values.add((*this)(item));
            Object array;
            array.set("values", values);
            result.set("arrayValue", array);
        }
        return result;
    }
};

Object anyValue(const otel::sdk::common::OwnedAttributeValue& value)
{
    return otel::nostd::visit(AnyValueVisitor{}, value);
}

template <typename Attributes> Array attributes(const Attributes& source)
{
    Array values;
    for (const auto& item : source)
    {
        Object attribute;
        attribute.set("key", item.first);
        attribute.set("value", anyValue(item.second));
        values.add(attribute);
    }
    return values;
}

std::string unixNanos(otel::common::SystemTimestamp timestamp)
{
    return std::to_string(
        std::chrono::duration_cast<std::chrono::nanoseconds>(timestamp.time_since_epoch()).count());
}

Object serializeSpan(const otel::sdk::trace::SpanData& span)
{
    Object result;
    result.set("traceId", base64Id(span.GetTraceId()));
    result.set("spanId", base64Id(span.GetSpanId()));
    if (span.GetParentSpanId().IsValid())
        result.set("parentSpanId", base64Id(span.GetParentSpanId()));
    result.set("name", std::string(span.GetName()));
    result.set("kind", static_cast<int>(span.GetSpanKind()) + 1);
    result.set("startTimeUnixNano", unixNanos(span.GetStartTime()));
    const otel::common::SystemTimestamp endTime(span.GetStartTime().time_since_epoch() +
                                                span.GetDuration());
    result.set("endTimeUnixNano", unixNanos(endTime));
    result.set("attributes", attributes(span.GetAttributes()));
    Array events;
    for (const auto& event : span.GetEvents())
    {
        Object value;
        value.set("name", event.GetName());
        value.set("timeUnixNano", unixNanos(event.GetTimestamp()));
        value.set("attributes", attributes(event.GetAttributes()));
        events.add(value);
    }
    result.set("events", events);
    Object status;
    status.set("code", span.GetStatus() == otel::trace::StatusCode::kOk      ? 1
                       : span.GetStatus() == otel::trace::StatusCode::kError ? 2
                                                                             : 0);
    status.set("message", std::string(span.GetDescription()));
    result.set("status", status);
    return result;
}

class OtlpHttpJsonExporter final : public otel::sdk::trace::SpanExporter
{
  public:
    OtlpHttpJsonExporter(std::string endpoint, std::map<std::string, std::string> headers)
        : _uri(std::move(endpoint)), _headers(std::move(headers))
    {
        if (_uri.getScheme() != "http" || _uri.getHost().empty())
            throw std::invalid_argument("OTLP endpoint must be an http URL");
        if (_uri.getPath().empty() || _uri.getPath() == "/")
            _uri.setPath("/v1/traces");
    }

    std::unique_ptr<otel::sdk::trace::Recordable> MakeRecordable() noexcept override
    {
        return std::make_unique<otel::sdk::trace::SpanData>();
    }

    otel::sdk::common::ExportResult
    Export(const otel::nostd::span<std::unique_ptr<otel::sdk::trace::Recordable>>& spans) noexcept
        override
    {
        try
        {
            std::lock_guard lock(_mutex);
            if (_shutdown)
                return otel::sdk::common::ExportResult::kFailure;
            Array spanValues;
            const otel::sdk::trace::SpanData* first = nullptr;
            for (const auto& record : spans)
            {
                const auto* span = dynamic_cast<const otel::sdk::trace::SpanData*>(record.get());
                if (!span)
                    return otel::sdk::common::ExportResult::kFailure;
                if (!first)
                    first = span;
                spanValues.add(serializeSpan(*span));
            }
            if (!first)
                return otel::sdk::common::ExportResult::kSuccess;
            Object resource;
            resource.set("attributes", attributes(first->GetResource().GetAttributes()));
            Object scope;
            scope.set("name", first->GetInstrumentationScope().GetName());
            scope.set("version", first->GetInstrumentationScope().GetVersion());
            Object scopeSpans;
            scopeSpans.set("scope", scope);
            scopeSpans.set("spans", spanValues);
            Array scopeValues;
            scopeValues.add(scopeSpans);
            Object resourceSpans;
            resourceSpans.set("resource", resource);
            resourceSpans.set("scopeSpans", scopeValues);
            Array resourceValues;
            resourceValues.add(resourceSpans);
            Object requestBody;
            requestBody.set("resourceSpans", resourceValues);
            std::ostringstream json;
            requestBody.stringify(json);
            const auto body = json.str();

            Poco::Net::HTTPClientSession session(_uri.getHost(),
                                                 _uri.getPort() ? _uri.getPort() : 80);
            Poco::Net::HTTPRequest request(Poco::Net::HTTPRequest::HTTP_POST,
                                           _uri.getPathAndQuery(),
                                           Poco::Net::HTTPMessage::HTTP_1_1);
            request.setContentType("application/json");
            request.setContentLength(body.size());
            for (const auto& header : _headers)
                request.set(header.first, header.second);
            session.sendRequest(request) << body;
            Poco::Net::HTTPResponse response;
            auto& responseBody = session.receiveResponse(response);
            std::ostringstream ignored;
            Poco::StreamCopier::copyStream(responseBody, ignored);
            return response.getStatus() >= 200 && response.getStatus() < 300
                       ? otel::sdk::common::ExportResult::kSuccess
                       : otel::sdk::common::ExportResult::kFailure;
        }
        catch (...)
        {
            return otel::sdk::common::ExportResult::kFailure;
        }
    }

    bool ForceFlush(std::chrono::microseconds) noexcept override { return true; }

    bool Shutdown(std::chrono::microseconds) noexcept override
    {
        std::lock_guard lock(_mutex);
        _shutdown = true;
        return true;
    }

  private:
    Poco::URI _uri;
    std::map<std::string, std::string> _headers;
    std::mutex _mutex;
    bool _shutdown{false};
};
} // namespace

std::unique_ptr<otel::sdk::trace::SpanExporter>
createOtlpHttpJsonExporter(std::string endpoint, std::map<std::string, std::string> headers)
{
    return std::make_unique<OtlpHttpJsonExporter>(std::move(endpoint), std::move(headers));
}
} // namespace PocoDDS::Observability
