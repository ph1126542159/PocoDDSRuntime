#include "PocoDDS/Observability/Metrics.h"

#include <Poco/Net/HTTPServer.h>
#include <Poco/Net/HTTPServerParams.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/Net/HTTPRequestHandlerFactory.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/Net/ServerSocket.h>
#include <Poco/StreamCopier.h>
#include <Poco/File.h>
#include <Poco/TemporaryFile.h>

#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

namespace
{
std::mutex receivedMutex;
std::string receivedPath;
std::string receivedBody;

class OtlpHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        std::string body;
        Poco::StreamCopier::copyToString(request.stream(), body);
        {
            std::lock_guard<std::mutex> lock(receivedMutex);
            receivedPath = request.getURI();
            receivedBody = std::move(body);
        }
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.send() << "{}";
    }
};

class OtlpFactory final : public Poco::Net::HTTPRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new OtlpHandler;
    }
};
}

int main()
{
    using PocoDDS::Observability::MetricKind;
    using PocoDDS::Observability::Metrics;
    using PocoDDS::Observability::MetricsOptions;

    MetricsOptions options;
    options.serviceName = "metrics-test";
    options.serviceInstanceId = "test-1";
    options.maximumSeries = 4;
    Poco::Net::ServerSocket socket(0);
    const auto port = socket.address().port();
    Poco::Net::HTTPServer collector(new OtlpFactory, socket,
                                    new Poco::Net::HTTPServerParams);
    collector.start();
    options.otlpHttpEndpoint = "http://127.0.0.1:" + std::to_string(port);
    Metrics::global().initialize(options);
    Metrics::global().addCounter("pdr.test.requests", 2, {{"result", "success"}});
    Metrics::global().addCounter("pdr.test.requests", 1, {{"result", "success"}});
    Metrics::global().recordHistogram("pdr.test.queue.depth", 7, {{"queue", "main"}});
    Metrics::global().recordHistogram("pdr.test.duration", 10, {{"operation", "probe"}});
    Metrics::global().recordHistogram("pdr.test.duration", 30, {{"operation", "probe"}});

    const auto snapshot = Metrics::global().snapshot();
    bool counterOk = false;
    bool queueOk = false;
    bool histogramOk = false;
    for (const auto& point : snapshot)
    {
        if (point.name == "pdr.test.requests" && point.kind == MetricKind::counter &&
            point.value == 3)
            counterOk = true;
        if (point.name == "pdr.test.queue.depth" && point.kind == MetricKind::histogram &&
            point.value == 7 && point.count == 1)
            queueOk = true;
        if (point.name == "pdr.test.duration" && point.kind == MetricKind::histogram &&
            point.count == 2 && point.sum == 40 && point.minimum == 10 && point.maximum == 30 &&
            point.bucketCounts.size() == point.explicitBounds.size() + 1)
            histogramOk = true;
    }
    const std::string json = Metrics::global().snapshotJson();
    const bool flushOk = Metrics::global().forceFlush();
    Metrics::global().shutdown();
    bool exportOk = false;
    {
        std::lock_guard<std::mutex> lock(receivedMutex);
        exportOk = receivedPath == "/v1/metrics" &&
                   receivedBody.find("resourceMetrics") != std::string::npos &&
                   receivedBody.find("bucketCounts") != std::string::npos &&
                   receivedBody.find("service.name") != std::string::npos;
    }
    const std::string cachePath = Poco::TemporaryFile::tempName() + "-metrics-cache";
    MetricsOptions outageOptions = options;
    Poco::Net::ServerSocket unavailableSocket(0);
    const auto unavailablePort = unavailableSocket.address().port();
    unavailableSocket.close();
    outageOptions.otlpHttpEndpoint =
        "http://127.0.0.1:" + std::to_string(unavailablePort);
    outageOptions.offlineCachePath = cachePath;
    outageOptions.exportInterval = std::chrono::hours(1);
    outageOptions.exportTimeout = std::chrono::milliseconds(250);
    Metrics::global().initialize(outageOptions);
    Metrics::global().addCounter("pdr.test.offline", 1);
    const bool outageDetected = !Metrics::global().forceFlush(std::chrono::milliseconds(250));
    Metrics::global().shutdown();
    std::vector<std::string> cachedFiles;
    const bool cached = Poco::File(cachePath).exists() &&
                        (Poco::File(cachePath).list(cachedFiles), !cachedFiles.empty());
    MetricsOptions recoveryOptions = options;
    recoveryOptions.offlineCachePath = cachePath;
    recoveryOptions.exportInterval = std::chrono::hours(1);
    recoveryOptions.exportTimeout = std::chrono::seconds(2);
    Metrics::global().initialize(recoveryOptions);
    Metrics::global().addCounter("pdr.test.recovery", 1);
    const bool recovered = Metrics::global().forceFlush(std::chrono::seconds(2));
    Metrics::global().shutdown();
    collector.stop();
    std::vector<std::string> replayedFiles;
    Poco::File(cachePath).list(replayedFiles);
    const bool replayed = replayedFiles.empty();
    Poco::File(cachePath).remove(true);

    if (!counterOk || !queueOk || !histogramOk ||
        !flushOk || !exportOk ||
        !outageDetected || !cached || !recovered || !replayed ||
        json.find("pdr.test.requests") == std::string::npos ||
        json.find("metrics-test") == std::string::npos)
        return 1;
    std::cout << "METRICS_TEST_PASS\n";
}
