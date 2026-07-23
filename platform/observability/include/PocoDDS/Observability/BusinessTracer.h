#pragma once

#include <cstddef>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::Observability
{
using Fields = std::map<std::string, std::string>;

struct TraceLog
{
    long long timestampUnixMicroseconds{0};
    std::string level;
    std::string message;
    Fields fields;
};

struct SpanSnapshot
{
    std::string businessName;
    std::string businessInstanceId;
    std::string operation;
    std::string serviceName;
    std::string bundleName;
    std::string hostName;
    unsigned long processId{0};
    std::string traceId;
    std::string spanId;
    std::string parentSpanId;
    std::string traceParent;
    std::string status{"running"};
    std::string errorCode;
    std::string errorMessage;
    long long startedUnixMicroseconds{0};
    long long endedUnixMicroseconds{0};
    long long durationNanoseconds{0};
    Fields inputs;
    Fields outputs;
    std::vector<TraceLog> logs;
};

struct DataPolicy
{
    std::size_t maximumValueLength{4096};
    std::size_t maximumFieldCount{64};
    std::vector<std::string> redactedKeyFragments{
        "password", "passwd", "secret", "token", "authorization", "cookie", "privatekey"};
    std::string redactedValue{"[REDACTED]"};
};

struct BusinessTracerOptions
{
    std::string bundleName;
    std::string otlpHttpEndpoint;
    std::map<std::string, std::string> otlpHeaders;
    DataPolicy dataPolicy;
    std::function<void(const SpanSnapshot&)> onChanged;
};

class BusinessTracer;

class BusinessSpan
{
public:
    class Impl;
    BusinessSpan();
    BusinessSpan(BusinessSpan&& other) noexcept;
    BusinessSpan& operator=(BusinessSpan&& other) noexcept;
    ~BusinessSpan();

    BusinessSpan(const BusinessSpan&) = delete;
    BusinessSpan& operator=(const BusinessSpan&) = delete;

    BusinessSpan startStep(const std::string& operation, const Fields& inputs = {});
    std::string traceParent() const;
    std::string businessInstanceId() const;
    void log(const std::string& message,
             const std::string& level = "info",
             const Fields& fields = {});
    void success(const Fields& outputs = {});
    void failure(const std::string& errorCode,
                 const std::string& errorMessage,
                 const Fields& outputs = {});
    void cancel(const std::string& reason = {});
    bool finished() const noexcept;

private:
    explicit BusinessSpan(std::shared_ptr<Impl> impl);
    std::shared_ptr<Impl> _impl;
    friend class BusinessTracer;
};

class BusinessTracer
{
public:
    class Impl;
    explicit BusinessTracer(std::string serviceName, BusinessTracerOptions options = {});
    ~BusinessTracer();

    BusinessTracer(const BusinessTracer&) = delete;
    BusinessTracer& operator=(const BusinessTracer&) = delete;

    BusinessSpan startBusiness(const std::string& businessName,
                               const Fields& inputs = {},
                               const std::string& businessInstanceId = {});
    BusinessSpan continueBusiness(const std::string& businessName,
                                  const std::string& operation,
                                  const std::string& parentTraceParent,
                                  const std::string& businessInstanceId,
                                  const Fields& inputs = {});

private:
    std::shared_ptr<Impl> _impl;
    BusinessSpan startSpan(const std::string& businessName,
                           const std::string& operation,
                           const Fields& inputs,
                           const std::string& parentTraceParent,
                           const std::string& businessInstanceId);
    friend class BusinessSpan;
};
} // namespace PocoDDS::Observability
