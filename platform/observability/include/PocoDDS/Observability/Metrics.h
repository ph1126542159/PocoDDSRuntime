#pragma once

#include <chrono>
#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::Observability
{
#if defined(_WIN32)
#if defined(PDRObservability_EXPORTS)
#define PDR_METRICS_API __declspec(dllexport)
#else
#define PDR_METRICS_API __declspec(dllimport)
#endif
#else
#define PDR_METRICS_API
#endif

using MetricAttributes = std::map<std::string, std::string>;

enum class MetricKind
{
    counter,
    histogram
};

struct MetricPoint
{
    std::string name;
    std::string description;
    std::string unit;
    MetricKind kind{MetricKind::counter};
    MetricAttributes attributes;
    double value{0};
    std::uint64_t count{0};
    double sum{0};
    double minimum{0};
    double maximum{0};
    std::vector<double> explicitBounds;
    std::vector<std::uint64_t> bucketCounts;
    std::int64_t timestampUnixNano{0};
};

struct MetricsOptions
{
    std::string serviceName{"pdr-runtime"};
    std::string serviceInstanceId;
    std::string otlpHttpEndpoint;
    std::string otlpCaCertificatePath;
    std::string otlpClientCertificatePath;
    std::string otlpClientKeyPath;
    bool otlpInsecureSkipVerify{false};
    std::string offlineCachePath{"data/metrics/otlp-cache"};
    std::size_t offlineCacheMaximumFiles{1000};
    std::chrono::milliseconds exportInterval{10000};
    std::chrono::milliseconds exportTimeout{5000};
    std::size_t maximumSeries{2000};
};

class Metrics
{
public:
    PDR_METRICS_API static Metrics& global();

    PDR_METRICS_API void initialize(MetricsOptions options);
    PDR_METRICS_API void shutdown() noexcept;
    [[nodiscard]] PDR_METRICS_API bool initialized() const noexcept;

    PDR_METRICS_API void addCounter(const std::string& name,
                    std::uint64_t value = 1,
                    MetricAttributes attributes = {},
                    const std::string& description = {},
                    const std::string& unit = "{operation}",
                    bool recordWithSdk = true);
    PDR_METRICS_API void recordHistogram(const std::string& name,
                         double value,
                         MetricAttributes attributes = {},
                         const std::string& description = {},
                         const std::string& unit = "ms",
                         bool recordWithSdk = true);

    [[nodiscard]] PDR_METRICS_API std::vector<MetricPoint> snapshot() const;
    [[nodiscard]] PDR_METRICS_API std::string snapshotJson() const;
    PDR_METRICS_API bool forceFlush(std::chrono::milliseconds timeout = std::chrono::milliseconds(5000));

private:
    PDR_METRICS_API Metrics();
    PDR_METRICS_API ~Metrics();
    Metrics(const Metrics&) = delete;
    Metrics& operator=(const Metrics&) = delete;

    class Impl;
    std::unique_ptr<Impl> _impl;
};

class ScopedMetricTimer
{
public:
    PDR_METRICS_API ScopedMetricTimer(std::string metric,
                      MetricAttributes attributes = {},
                      std::string description = {},
                      std::string unit = "ms");
    PDR_METRICS_API ~ScopedMetricTimer();
    ScopedMetricTimer(const ScopedMetricTimer&) = delete;
    ScopedMetricTimer& operator=(const ScopedMetricTimer&) = delete;

private:
    std::string _metric;
    MetricAttributes _attributes;
    std::string _description;
    std::string _unit;
    std::chrono::steady_clock::time_point _started;
};
}
