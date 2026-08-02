#include "PocoDDS/Observability/Metrics.h"

#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/Net/HTTPClientSession.h>
#include <Poco/Net/HTTPSClientSession.h>
#include <Poco/Net/Context.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/StreamCopier.h>
#include <Poco/Timestamp.h>
#include <Poco/URI.h>
#include <Poco/DirectoryIterator.h>
#include <Poco/File.h>
#include <Poco/FileStream.h>

#include <opentelemetry/metrics/meter.h>
#include <opentelemetry/metrics/provider.h>
#include <opentelemetry/context/context.h>
#include <opentelemetry/common/key_value_iterable_view.h>
#include <opentelemetry/sdk/metrics/meter_context_factory.h>
#include <opentelemetry/sdk/metrics/meter_provider_factory.h>
#include <opentelemetry/sdk/metrics/view/view_registry.h>
#include <opentelemetry/sdk/metrics/export/periodic_exporting_metric_reader_factory.h>
#include <opentelemetry/exporters/otlp/otlp_http_metric_exporter_factory.h>
#include <opentelemetry/exporters/otlp/otlp_http_metric_exporter_options.h>
#include <opentelemetry/sdk/resource/resource.h>

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <limits>
#include <mutex>
#include <sstream>
#include <thread>
#include <unordered_map>

namespace PocoDDS::Observability
{
// The registry is the process-wide composition point for SDK instruments,
// local diagnostics and OTLP export.
namespace otel = opentelemetry;
namespace metricsSdk = opentelemetry::sdk::metrics;

namespace
{
std::string seriesKey(const std::string& name, const MetricAttributes& attributes)
{
    std::string key = name;
    for (const auto& attribute : attributes)
    {
        key.push_back('\x1f');
        key += attribute.first;
        key.push_back('=');
        key += attribute.second;
    }
    return key;
}

const char* kindName(MetricKind kind)
{
    switch (kind)
    {
    case MetricKind::counter: return "counter";
    case MetricKind::histogram: return "histogram";
    }
    return "unknown";
}

Poco::JSON::Object::Ptr attributesJson(const MetricAttributes& attributes)
{
    auto result = new Poco::JSON::Object;
    for (const auto& attribute : attributes)
        result->set(attribute.first, attribute.second);
    return result;
}
}

class Metrics::Impl
{
public:
    ~Impl() { shutdown(); }

    bool isActive() const noexcept { return active; }

    void initialize(MetricsOptions requested)
    {
        shutdown();
        if (requested.maximumSeries == 0)
            requested.maximumSeries = 1;
        options = std::move(requested);
        {
            std::lock_guard<std::mutex> lock(mutex);
            points.clear();
            droppedSeries = 0;
        }

        const auto resource = otel::sdk::resource::Resource::Create({
            {"service.name", options.serviceName},
            {"service.instance.id", options.serviceInstanceId}});
        auto context = metricsSdk::MeterContextFactory::Create(
            std::make_unique<metricsSdk::ViewRegistry>(), resource);
        auto sdkProvider = metricsSdk::MeterProviderFactory::Create(std::move(context));
        if (!options.otlpHttpEndpoint.empty())
        {
            otel::exporter::otlp::OtlpHttpMetricExporterOptions exporterOptions;
            Poco::URI endpoint(options.otlpHttpEndpoint);
            if (endpoint.getPath().empty() || endpoint.getPath() == "/")
                endpoint.setPath("/v1/metrics");
            exporterOptions.url = endpoint.toString();
            exporterOptions.content_type = otel::exporter::otlp::HttpRequestContentType::kJson;
            exporterOptions.timeout = options.exportTimeout;
            exporterOptions.ssl_insecure_skip_verify = options.otlpInsecureSkipVerify;
            exporterOptions.ssl_ca_cert_path = options.otlpCaCertificatePath;
            exporterOptions.ssl_client_cert_path = options.otlpClientCertificatePath;
            exporterOptions.ssl_client_key_path = options.otlpClientKeyPath;
            exporterOptions.retry_policy_max_attempts = 5;
            exporterOptions.retry_policy_initial_backoff = std::chrono::seconds(1);
            exporterOptions.retry_policy_max_backoff = std::chrono::seconds(30);
            exporterOptions.retry_policy_backoff_multiplier = 2.0F;
            auto metricExporter = otel::exporter::otlp::OtlpHttpMetricExporterFactory::Create(
                exporterOptions);
            metricsSdk::PeriodicExportingMetricReaderOptions readerOptions;
            readerOptions.export_interval_millis = options.exportInterval;
            readerOptions.export_timeout_millis = options.exportTimeout;
            auto reader = metricsSdk::PeriodicExportingMetricReaderFactory::Create(
                std::move(metricExporter), readerOptions);
            sdkProvider->AddMetricReader(std::shared_ptr<metricsSdk::MetricReader>(reader.release()));
        }
        provider = otel::nostd::shared_ptr<otel::metrics::MeterProvider>(sdkProvider.release());
        otel::metrics::Provider::SetMeterProvider(provider);
        meter = provider->GetMeter("PocoDDSRuntime", "1.0.0");
        // Instruments are created on the composition thread. Some older
        // OpenTelemetry C++ builds serialize instrument creation with SDK
        // collection; avoiding first-use creation on request/DDS callbacks
        // also removes latency from those hot paths.
        for (const std::string name : {
                 "pdr.runtime.starts", "pdr.runtime.shutdowns",
                 "pdr.dds.runtime.starts", "pdr.dds.messages.received",
                 "pdr.dds.messages.published", "pdr.dds.handler.errors",
                 "pdr.dds.publish.errors", "pdr.dds.service.cache.hits",
                 "pdr.dds.service.requests", "pdr.dds.service.response.errors",
                 "pdr.device.starts", "pdr.device.commands",
                 "pdr.workflow.executions", "pdr.workflow.compensations",
                 "pdr.protocol.operations", "pdr.protocol.io",
                 "pdr.health.component.samples",
                 "pdr.diagnostics.failure.samples",
                 "pdr.alert.transitions",
                 "pdr.alert.delivery",
                 "http.server.request.count", "http.server.response.count"})
            counters.emplace(name, meter->CreateUInt64Counter(name));
        for (const std::string name : {
                 "pdr.dds.publish.duration", "pdr.dds.service.duration",
                 "pdr.device.command.duration", "pdr.workflow.duration",
                 "pdr.protocol.operation.duration", "http.server.request.duration",
                 "pdr.management.tasks.queue.depth",
                 "pdr.management.tasks.workers.active",
                 "pdr.management.tasks.resource.waiting",
                 "pdr.management.tasks.queue.utilization",
                 "pdr.management.tasks.wait.max"})
            histograms.emplace(name, meter->CreateDoubleHistogram(name));
        active = true;
        if (!options.otlpHttpEndpoint.empty())
        {
            Poco::File(options.offlineCachePath).createDirectories();
            exporter = std::thread([this] { exportLoop(); });
        }
    }

    void shutdown() noexcept
    {
        active = false;
        wake.notify_all();
        if (exporter.joinable()) exporter.join();
        if (provider)
        {
            auto* sdkProvider = dynamic_cast<metricsSdk::MeterProvider*>(provider.get());
            if (sdkProvider)
                sdkProvider->Shutdown(std::chrono::microseconds(
                    std::chrono::duration_cast<std::chrono::microseconds>(options.exportTimeout)));
        }
        meter = {};
        provider = {};
        counters.clear();
        histograms.clear();
    }

    bool addSeries(const std::string& key, MetricPoint point)
    {
        const auto found = points.find(key);
        if (found != points.end())
            return true;
        if (points.size() >= options.maximumSeries)
        {
            ++droppedSeries;
            return false;
        }
        points.emplace(key, std::move(point));
        return true;
    }

    void addCounter(const std::string& name, std::uint64_t value,
                    MetricAttributes attributes, const std::string& description,
                    const std::string& unit, bool recordWithSdk)
    {
        if (!active || name.empty()) return;
        if (meter && recordWithSdk)
        {
            std::lock_guard<std::mutex> instrumentLock(instrumentMutex);
            auto& counter = counters[name];
            if (!counter)
                counter = meter->CreateUInt64Counter(name, description, unit);
            const otel::common::KeyValueIterableView<MetricAttributes> labels(attributes);
            counter->Add(value, labels, otel::context::Context{});
        }
        std::unique_lock<std::mutex> lock(mutex, std::try_to_lock);
        if (!lock.owns_lock()) return;
        const auto key = seriesKey(name, attributes);
        MetricPoint initial{name, description, unit, MetricKind::counter, attributes};
        if (!addSeries(key, std::move(initial))) return;
        auto& point = points[key];
        point.value += static_cast<double>(value);
        point.timestampUnixNano = nowUnixNano();
    }

    void recordHistogram(const std::string& name, double value, MetricAttributes attributes,
                         const std::string& description, const std::string& unit,
                         bool recordWithSdk)
    {
        if (!active || name.empty()) return;
        if (meter && recordWithSdk)
        {
            std::lock_guard<std::mutex> instrumentLock(instrumentMutex);
            auto& histogram = histograms[name];
            if (!histogram)
                histogram = meter->CreateDoubleHistogram(name, description, unit);
            const otel::common::KeyValueIterableView<MetricAttributes> labels(attributes);
            histogram->Record(value, labels, otel::context::Context{});
        }
        std::unique_lock<std::mutex> lock(mutex, std::try_to_lock);
        if (!lock.owns_lock()) return;
        const auto key = seriesKey(name, attributes);
        MetricPoint initial{name, description, unit, MetricKind::histogram, attributes};
        if (!addSeries(key, std::move(initial))) return;
        auto& point = points[key];
        if (point.explicitBounds.empty())
        {
            point.explicitBounds = {1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000};
            point.bucketCounts.assign(point.explicitBounds.size() + 1, 0);
        }
        point.value = value;
        point.sum += value;
        if (point.count == 0)
        {
            point.minimum = value;
            point.maximum = value;
        }
        else
        {
            if (value < point.minimum) point.minimum = value;
            if (value > point.maximum) point.maximum = value;
        }
        ++point.count;
        const auto bucket = std::upper_bound(point.explicitBounds.begin(),
                                             point.explicitBounds.end(), value);
        ++point.bucketCounts[static_cast<std::size_t>(bucket - point.explicitBounds.begin())];
        point.timestampUnixNano = nowUnixNano();
    }

    std::vector<MetricPoint> snapshot() const
    {
        std::lock_guard<std::mutex> lock(mutex);
        std::vector<MetricPoint> result;
        result.reserve(points.size() + (droppedSeries ? 1 : 0));
        for (const auto& item : points)
            result.push_back(item.second);
        if (droppedSeries)
        {
            MetricPoint dropped{"pdr.metrics.series.dropped", "Metric series rejected by cardinality guard", "{series}", MetricKind::counter};
            dropped.value = static_cast<double>(droppedSeries);
            dropped.timestampUnixNano = nowUnixNano();
            result.push_back(std::move(dropped));
        }
        return result;
    }

    std::string json() const
    {
        Poco::JSON::Object root;
        root.set("serviceName", options.serviceName);
        root.set("serviceInstanceId", options.serviceInstanceId);
        Poco::JSON::Array::Ptr values = new Poco::JSON::Array;
        for (const auto& point : snapshot())
        {
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("name", point.name);
            item->set("description", point.description);
            item->set("unit", point.unit);
            item->set("kind", kindName(point.kind));
            item->set("attributes", attributesJson(point.attributes));
            item->set("value", point.value);
            item->set("count", point.count);
            item->set("sum", point.sum);
            item->set("minimum", point.minimum);
            item->set("maximum", point.maximum);
            if (point.kind == MetricKind::histogram)
            {
                Poco::JSON::Array::Ptr bounds = new Poco::JSON::Array;
                for (const auto bound : point.explicitBounds) bounds->add(bound);
                Poco::JSON::Array::Ptr buckets = new Poco::JSON::Array;
                for (const auto count : point.bucketCounts) buckets->add(count);
                item->set("explicitBounds", bounds);
                item->set("bucketCounts", buckets);
            }
            item->set("timestampUnixNano", std::to_string(point.timestampUnixNano));
            values->add(item);
        }
        root.set("metrics", values);
        std::ostringstream output;
        root.stringify(output);
        return output.str();
    }

    bool flush(std::chrono::milliseconds timeout)
    {
        if (options.otlpHttpEndpoint.empty()) return true;
        auto* sdkProvider = dynamic_cast<metricsSdk::MeterProvider*>(provider.get());
        const bool exported = sdkProvider && sdkProvider->ForceFlush(std::chrono::microseconds(
            std::chrono::duration_cast<std::chrono::microseconds>(timeout)));
        if (!exported)
        {
            cachePayload(otlpJson());
            addCounter("pdr.metrics.export.attempts", 1, {{"result", "failed"}},
                       "Metric export attempts", "{attempt}", false);
            return false;
        }
        addCounter("pdr.metrics.export.attempts", 1, {{"result", "success"}},
                   "Metric export attempts", "{attempt}", false);
        replayCache(timeout);
        return true;
    }

private:
    static std::int64_t nowUnixNano()
    {
        return Poco::Timestamp().epochMicroseconds() * 1000;
    }

    std::string otlpJson() const
    {
        Poco::JSON::Array::Ptr resourceAttributes = new Poco::JSON::Array;
        for (const auto& attribute : MetricAttributes{{"service.name", options.serviceName},
                                                       {"service.instance.id", options.serviceInstanceId}})
        {
            Poco::JSON::Object::Ptr entry = new Poco::JSON::Object;
            entry->set("key", attribute.first);
            Poco::JSON::Object::Ptr value = new Poco::JSON::Object;
            value->set("stringValue", attribute.second);
            entry->set("value", value);
            resourceAttributes->add(entry);
        }
        Poco::JSON::Array::Ptr metrics = new Poco::JSON::Array;
        for (const auto& point : snapshot())
        {
            Poco::JSON::Object::Ptr metric = new Poco::JSON::Object;
            metric->set("name", point.name);
            metric->set("description", point.description);
            metric->set("unit", point.unit);
            Poco::JSON::Array::Ptr dataPoints = new Poco::JSON::Array;
            Poco::JSON::Object::Ptr dataPoint = new Poco::JSON::Object;
            Poco::JSON::Array::Ptr attributes = new Poco::JSON::Array;
            for (const auto& attribute : point.attributes)
            {
                Poco::JSON::Object::Ptr entry = new Poco::JSON::Object;
                entry->set("key", attribute.first);
                Poco::JSON::Object::Ptr value = new Poco::JSON::Object;
                value->set("stringValue", attribute.second);
                entry->set("value", value);
                attributes->add(entry);
            }
            dataPoint->set("attributes", attributes);
            dataPoint->set("timeUnixNano", std::to_string(point.timestampUnixNano));
            if (point.kind == MetricKind::histogram)
            {
                dataPoint->set("count", std::to_string(point.count));
                dataPoint->set("sum", point.sum);
                dataPoint->set("min", point.minimum);
                dataPoint->set("max", point.maximum);
                Poco::JSON::Array::Ptr bounds = new Poco::JSON::Array;
                for (const auto bound : point.explicitBounds) bounds->add(bound);
                Poco::JSON::Array::Ptr buckets = new Poco::JSON::Array;
                for (const auto count : point.bucketCounts)
                    buckets->add(std::to_string(count));
                dataPoint->set("explicitBounds", bounds);
                dataPoint->set("bucketCounts", buckets);
                dataPoints->add(dataPoint);
                Poco::JSON::Object::Ptr histogram = new Poco::JSON::Object;
                histogram->set("aggregationTemporality", 2);
                histogram->set("dataPoints", dataPoints);
                metric->set("histogram", histogram);
            }
            else if (point.kind == MetricKind::counter)
            {
                dataPoint->set("asDouble", point.value);
                dataPoints->add(dataPoint);
                Poco::JSON::Object::Ptr sum = new Poco::JSON::Object;
                sum->set("aggregationTemporality", 2);
                sum->set("isMonotonic", true);
                sum->set("dataPoints", dataPoints);
                metric->set("sum", sum);
            }
            metrics->add(metric);
        }
        Poco::JSON::Object::Ptr scope = new Poco::JSON::Object;
        scope->set("name", "PocoDDSRuntime");
        scope->set("version", "1.0.0");
        Poco::JSON::Object::Ptr scopeMetrics = new Poco::JSON::Object;
        scopeMetrics->set("scope", scope);
        scopeMetrics->set("metrics", metrics);
        Poco::JSON::Array::Ptr scopeMetricsArray = new Poco::JSON::Array;
        scopeMetricsArray->add(scopeMetrics);
        Poco::JSON::Object::Ptr resource = new Poco::JSON::Object;
        resource->set("attributes", resourceAttributes);
        Poco::JSON::Object::Ptr resourceMetric = new Poco::JSON::Object;
        resourceMetric->set("resource", resource);
        resourceMetric->set("scopeMetrics", scopeMetricsArray);
        Poco::JSON::Array::Ptr resourceMetrics = new Poco::JSON::Array;
        resourceMetrics->add(resourceMetric);
        Poco::JSON::Object root;
        root.set("resourceMetrics", resourceMetrics);
        std::ostringstream output;
        root.stringify(output);
        return output.str();
    }

    std::unique_ptr<Poco::Net::HTTPClientSession> createSession(
        const Poco::URI& uri, std::chrono::milliseconds timeout) const
    {
        std::unique_ptr<Poco::Net::HTTPClientSession> session;
        if (uri.getScheme() == "https")
        {
            Poco::Net::Context::Params params;
            params.caLocation = options.otlpCaCertificatePath;
            params.certificateFile = options.otlpClientCertificatePath;
            params.privateKeyFile = options.otlpClientKeyPath;
            params.verificationMode = options.otlpInsecureSkipVerify
                ? Poco::Net::Context::VERIFY_NONE : Poco::Net::Context::VERIFY_STRICT;
            params.loadDefaultCAs = params.caLocation.empty();
            auto context = new Poco::Net::Context(Poco::Net::Context::CLIENT_USE, params);
            session = std::make_unique<Poco::Net::HTTPSClientSession>(
                uri.getHost(), uri.getPort(), context);
        }
        else
            session = std::make_unique<Poco::Net::HTTPClientSession>(uri.getHost(), uri.getPort());
        session->setTimeout(Poco::Timespan(
            std::chrono::duration_cast<std::chrono::microseconds>(timeout).count()));
        return session;
    }

    bool postPayload(const std::string& payload, std::chrono::milliseconds timeout) const
    {
        try
        {
            Poco::URI uri(options.otlpHttpEndpoint);
            if (uri.getPath().empty() || uri.getPath() == "/") uri.setPath("/v1/metrics");
            auto session = createSession(uri, timeout);
            Poco::Net::HTTPRequest request(Poco::Net::HTTPRequest::HTTP_POST,
                                           uri.getPathEtc(), Poco::Net::HTTPMessage::HTTP_1_1);
            request.setContentType("application/json");
            request.setContentLength(payload.size());
            session->sendRequest(request) << payload;
            Poco::Net::HTTPResponse response;
            auto& responseStream = session->receiveResponse(response);
            std::string ignored;
            Poco::StreamCopier::copyToString(responseStream, ignored);
            return response.getStatus() >= 200 && response.getStatus() < 300;
        }
        catch (...) { return false; }
    }

    std::vector<std::string> cacheFiles() const
    {
        std::vector<std::string> files;
        Poco::File directory(options.offlineCachePath);
        if (!directory.exists()) return files;
        for (Poco::DirectoryIterator it(directory); it != Poco::DirectoryIterator(); ++it)
            if (it->isFile() && it.name().find(".otlp.json") != std::string::npos)
                files.push_back(it.path().toString());
        std::sort(files.begin(), files.end());
        return files;
    }

    void cachePayload(const std::string& payload) noexcept
    {
        try
        {
            Poco::File(options.offlineCachePath).createDirectories();
            auto files = cacheFiles();
            while (files.size() >= options.offlineCacheMaximumFiles)
            {
                Poco::File(files.front()).remove();
                files.erase(files.begin());
            }
            const std::string file = options.offlineCachePath + "/" +
                std::to_string(nowUnixNano()) + ".otlp.json";
            Poco::FileOutputStream output(file, std::ios::binary);
            output << payload;
            output.close();
        }
        catch (...) {}
    }

    void replayCache(std::chrono::milliseconds timeout)
    {
        auto files = cacheFiles();
        std::size_t replayed = 0;
        for (const auto& file : files)
        {
            Poco::FileInputStream input(file, std::ios::binary);
            std::string payload;
            Poco::StreamCopier::copyToString(input, payload);
            if (!postPayload(payload, timeout)) break;
            input.close();
            Poco::File(file).remove();
            ++replayed;
        }
        if (replayed)
            addCounter("pdr.metrics.offline.replayed", replayed, {},
                       "Offline metric payloads replayed", "{payload}", false);
        recordHistogram("pdr.metrics.offline.cache.depth",
                        static_cast<double>(cacheFiles().size()), {},
                        "Offline metric payload cache depth", "{payload}", false);
    }

    void exportLoop()
    {
        std::unique_lock<std::mutex> lock(exportMutex);
        while (active)
        {
            if (wake.wait_for(lock, options.exportInterval, [this] { return !active.load(); })) break;
            lock.unlock();
            flush(options.exportTimeout);
            lock.lock();
        }
    }

    MetricsOptions options;
    mutable std::mutex mutex;
    std::unordered_map<std::string, MetricPoint> points;
    std::uint64_t droppedSeries{0};
    std::mutex instrumentMutex;
    std::unordered_map<std::string, otel::nostd::unique_ptr<otel::metrics::Counter<std::uint64_t>>> counters;
    std::unordered_map<std::string, otel::nostd::unique_ptr<otel::metrics::Histogram<double>>> histograms;
    otel::nostd::shared_ptr<otel::metrics::MeterProvider> provider;
    otel::nostd::shared_ptr<otel::metrics::Meter> meter;
    std::atomic<bool> active{false};
    std::thread exporter;
    std::mutex exportMutex;
    std::condition_variable wake;
};

Metrics& Metrics::global()
{
    static Metrics metrics;
    return metrics;
}

Metrics::Metrics(): _impl(std::make_unique<Impl>()) {}
Metrics::~Metrics() = default;
void Metrics::initialize(MetricsOptions options) { _impl->initialize(std::move(options)); }
void Metrics::shutdown() noexcept { _impl->shutdown(); }
bool Metrics::initialized() const noexcept { return _impl->isActive(); }
void Metrics::addCounter(const std::string& name, std::uint64_t value,
                         MetricAttributes attributes, const std::string& description,
                         const std::string& unit, bool recordWithSdk)
{ _impl->addCounter(name, value, std::move(attributes), description, unit, recordWithSdk); }
void Metrics::recordHistogram(const std::string& name, double value,
                              MetricAttributes attributes, const std::string& description,
                              const std::string& unit, bool recordWithSdk)
{ _impl->recordHistogram(name, value, std::move(attributes), description, unit, recordWithSdk); }
std::vector<MetricPoint> Metrics::snapshot() const { return _impl->snapshot(); }
std::string Metrics::snapshotJson() const { return _impl->json(); }
bool Metrics::forceFlush(std::chrono::milliseconds timeout) { return _impl->flush(timeout); }

ScopedMetricTimer::ScopedMetricTimer(std::string metric, MetricAttributes attributes,
                                     std::string description, std::string unit)
    : _metric(std::move(metric)), _attributes(std::move(attributes)),
      _description(std::move(description)), _unit(std::move(unit)),
      _started(std::chrono::steady_clock::now()) {}

ScopedMetricTimer::~ScopedMetricTimer()
{
    const auto duration = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - _started).count();
    Metrics::global().recordHistogram(_metric, duration, std::move(_attributes),
                                      _description, _unit, true);
}
}
