#pragma once

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::Observability
{

struct CompletedSpan
{
    std::string name;
    std::string traceId;
    std::string spanId;
    std::string parentSpanId;
    std::string status;
    long long durationNanoseconds = 0;
};

struct BusinessTracerOptions
{
    std::string otlpHttpEndpoint;
    std::map<std::string, std::string> otlpHeaders;
};

class BusinessSpan
{
  public:
    BusinessSpan();
    BusinessSpan(BusinessSpan&& other) noexcept;
    BusinessSpan& operator=(BusinessSpan&& other) noexcept;
    ~BusinessSpan();

    BusinessSpan(const BusinessSpan&) = delete;
    BusinessSpan& operator=(const BusinessSpan&) = delete;

    std::string traceParent() const;
    void addLog(const std::string& message);
    void finish(const std::string& status, const std::map<std::string, std::string>& outputs = {});

  private:
    class Impl;
    explicit BusinessSpan(std::unique_ptr<Impl> impl);
    std::unique_ptr<Impl> _impl;

    friend class BusinessTracer;
};

class BusinessTracer
{
  public:
    class Impl;

    explicit BusinessTracer(std::string serviceName);
    BusinessTracer(std::string serviceName, BusinessTracerOptions options);
    ~BusinessTracer();

    BusinessSpan start(const std::string& operation,
                       const std::map<std::string, std::string>& inputs = {},
                       const std::string& parentTraceParent = {});
    std::vector<CompletedSpan> drain();

  private:
    std::shared_ptr<Impl> _impl;
};

} // namespace PocoDDS::Observability
