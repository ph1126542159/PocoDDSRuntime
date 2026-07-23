#include "PocoDDS/Observability/TraceSerialization.h"

#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>

#include <sstream>

namespace PocoDDS::Observability
{
namespace
{
using Poco::JSON::Array;
using Poco::JSON::Object;

Object fields(const Fields& source)
{
    Object result;
    for (const auto& item : source)
        result.set(item.first, item.second);
    return result;
}

Fields fields(const Object::Ptr& source)
{
    Fields result;
    if (source)
        for (const auto& item : *source)
            result[item.first] = item.second.convert<std::string>();
    return result;
}
} // namespace

std::string serializeSpanSnapshot(const SpanSnapshot& span)
{
    Object value;
    value.set("businessName", span.businessName);
    value.set("businessInstanceId", span.businessInstanceId);
    value.set("operation", span.operation);
    value.set("serviceName", span.serviceName);
    value.set("bundleName", span.bundleName);
    value.set("hostName", span.hostName);
    value.set("processId", span.processId);
    value.set("traceId", span.traceId);
    value.set("spanId", span.spanId);
    value.set("parentSpanId", span.parentSpanId);
    value.set("traceParent", span.traceParent);
    value.set("status", span.status);
    value.set("errorCode", span.errorCode);
    value.set("errorMessage", span.errorMessage);
    value.set("startedUnixMicroseconds", span.startedUnixMicroseconds);
    value.set("endedUnixMicroseconds", span.endedUnixMicroseconds);
    value.set("durationNanoseconds", span.durationNanoseconds);
    value.set("inputs", fields(span.inputs));
    value.set("outputs", fields(span.outputs));
    Array logs;
    for (const auto& log : span.logs)
    {
        Object record;
        record.set("timestampUnixMicroseconds", log.timestampUnixMicroseconds);
        record.set("level", log.level);
        record.set("message", log.message);
        record.set("fields", fields(log.fields));
        logs.add(record);
    }
    value.set("logs", logs);
    std::ostringstream output;
    value.stringify(output);
    return output.str();
}

SpanSnapshot deserializeSpanSnapshot(const std::string& json)
{
    const auto value = Poco::JSON::Parser().parse(json).extract<Object::Ptr>();
    SpanSnapshot span;
    span.businessName = value->getValue<std::string>("businessName");
    span.businessInstanceId = value->getValue<std::string>("businessInstanceId");
    span.operation = value->getValue<std::string>("operation");
    span.serviceName = value->getValue<std::string>("serviceName");
    span.bundleName = value->optValue<std::string>("bundleName", "");
    span.hostName = value->optValue<std::string>("hostName", "");
    span.processId = value->optValue<unsigned long>("processId", 0);
    span.traceId = value->getValue<std::string>("traceId");
    span.spanId = value->getValue<std::string>("spanId");
    span.parentSpanId = value->optValue<std::string>("parentSpanId", "");
    span.traceParent = value->optValue<std::string>("traceParent", "");
    span.status = value->getValue<std::string>("status");
    span.errorCode = value->optValue<std::string>("errorCode", "");
    span.errorMessage = value->optValue<std::string>("errorMessage", "");
    span.startedUnixMicroseconds = value->getValue<long long>("startedUnixMicroseconds");
    span.endedUnixMicroseconds = value->getValue<long long>("endedUnixMicroseconds");
    span.durationNanoseconds = value->getValue<long long>("durationNanoseconds");
    span.inputs = fields(value->getObject("inputs"));
    span.outputs = fields(value->getObject("outputs"));
    if (const auto logs = value->getArray("logs"))
    {
        for (std::size_t index = 0; index < logs->size(); ++index)
        {
            const auto record = logs->getObject(static_cast<unsigned>(index));
            TraceLog log;
            log.timestampUnixMicroseconds =
                record->getValue<long long>("timestampUnixMicroseconds");
            log.level = record->getValue<std::string>("level");
            log.message = record->getValue<std::string>("message");
            log.fields = fields(record->getObject("fields"));
            span.logs.push_back(std::move(log));
        }
    }
    return span;
}
} // namespace PocoDDS::Observability
