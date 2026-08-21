//
// MacchinaServer.cpp
//
// The PocoDDSRuntime bundle and service container entry point.
// Derived from the macchina.io EDGE server composition-root pattern.
//

#include "Poco/DataURIStreamFactory.h"
#include "Poco/DateTimeFormatter.h"
#include "Poco/Environment.h"
#include "Poco/ErrorHandler.h"
#include "Poco/Exception.h"
#include "Poco/Formatter.h"
#include "Poco/Instantiator.h"
#include "Poco/LocalDateTime.h"
#include "Poco/LoggingFactory.h"
#include "Poco/Message.h"
#include "Poco/NumberParser.h"
#include "Poco/OSP/Bundle.h"
#include "Poco/OSP/BundleLoader.h"
#include "Poco/OSP/OSPSubsystem.h"
#include "Poco/OSP/ServiceRegistry.h"
#include "Poco/ThreadPool.h"
#include "Poco/Timestamp.h"
#include "Poco/Util/HelpFormatter.h"
#include "Poco/Util/LoggingConfigurator.h"
#include "Poco/Util/Option.h"
#include "Poco/Util/OptionSet.h"
#include "Poco/Util/ServerApplication.h"
#include "PocoDDS/BundleManagement/BundleManager.h"
#include "PocoDDS/Configuration/ConfigurationValidator.h"
#include "PocoDDS/ProcessManagement/SubprocessManager.h"
#if defined(PDR_ENABLE_OBSERVABILITY)
#include "PocoDDS/DDS/Runtime.h"
#include "PocoDDS/Observability/BusinessTracer.h"
#include "PocoDDS/Observability/Metrics.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"
#include "PocoDDS/Observability/TraceSerialization.h"
#include "PocoDDS/Observability/TraceStore.h"
#endif

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cstring>
#include <iostream>
#include <mutex>
#include <memory>
#include <string>
#include <thread>
#include <unordered_set>
#include <utility>
#include <vector>

namespace
{
class AlignedLogFormatter final : public Poco::Formatter
{
  public:
    void format(const Poco::Message& message, std::string& text) override
    {
        text.clear();
        text.reserve(message.getText().size() + _moduleWidth + 48);
        text.push_back('[');
        Poco::DateTimeFormatter::append(text, Poco::LocalDateTime(message.getTime()),
                                        "%Y-%m-%d %H-%M-%S.%i");
        text.append("][").append(priorityName(message.getPriority())).append("][");

        const std::string& source = message.getSource();
        const std::size_t visibleLength = std::min(source.size(), _moduleWidth);
        text.append(source, 0, visibleLength);
        if (visibleLength < _moduleWidth)
            text.append(_moduleWidth - visibleLength, ' ');
        text.append("]: ").append(message.getText());
    }

    void setProperty(const std::string& name, const std::string& value) override
    {
        if (name == "moduleWidth")
        {
            _moduleWidth = Poco::NumberParser::parseUnsigned(value);
            if (_moduleWidth == 0)
                throw Poco::InvalidArgumentException("moduleWidth must be greater than zero");
        }
        else
            Poco::Formatter::setProperty(name, value);
    }

    std::string getProperty(const std::string& name) const override
    {
        if (name == "moduleWidth")
            return std::to_string(_moduleWidth);
        return Poco::Formatter::getProperty(name);
    }

  private:
    static const char* priorityName(Poco::Message::Priority priority)
    {
        switch (priority)
        {
        case Poco::Message::PRIO_FATAL:
            return "FTL";
        case Poco::Message::PRIO_CRITICAL:
            return "CRT";
        case Poco::Message::PRIO_ERROR:
            return "ERR";
        case Poco::Message::PRIO_WARNING:
            return "WRN";
        case Poco::Message::PRIO_NOTICE:
            return "NTC";
        case Poco::Message::PRIO_INFORMATION:
            return "INF";
        case Poco::Message::PRIO_DEBUG:
            return "DBG";
        case Poco::Message::PRIO_TRACE:
            return "TRC";
        default:
            return "UNK";
        }
    }

    std::size_t _moduleWidth{20};
};

class MacchinaServer final : public Poco::Util::ServerApplication
{
  public:
    MacchinaServer() : _errorHandler(*this), _osp(new Poco::OSP::OSPSubsystem)
    {
        Poco::LoggingFactory::defaultFactory().registerFormatterClass(
            "PDRAlignedFormatter",
            new Poco::Instantiator<AlignedLogFormatter, Poco::Formatter>);
        Poco::DataURIStreamFactory::registerFactory();
        Poco::ErrorHandler::set(&_errorHandler);
        addSubsystem(_osp);
    }

    ~MacchinaServer() override
    {
        Poco::ThreadPool::defaultPool().joinAll();
        Poco::DataURIStreamFactory::unregisterFactory();
    }

    Poco::OSP::ServiceRegistry& serviceRegistry() { return _osp->serviceRegistry(); }

  protected:
    class RuntimeErrorHandler final : public Poco::ErrorHandler
    {
      public:
        explicit RuntimeErrorHandler(MacchinaServer& application) : _application(application) {}

        void exception(const Poco::Exception& exception) override
        {
            if (std::strcmp(exception.name(), "Connection reset by peer") != 0 &&
                std::strcmp(exception.name(), "Timeout") != 0)
                log(exception.displayText());
        }

        void exception(const std::exception& exception) override { log(exception.what()); }
        void exception() override { log("unknown exception"); }

      private:
        void log(const std::string& message)
        {
            _application.logger().notice("A thread was terminated by an unhandled exception: " +
                                         message);
        }

        MacchinaServer& _application;
    };

    void initialize(Application& self) override
    {
        if (!_skipDefaultConfig)
            loadConfiguration();
        for (const auto& configuration : _configurationFiles)
            loadConfiguration(configuration);
        PocoDDS::Configuration::ConfigurationValidator().validateOrThrow(config());

        // Custom configuration files are loaded by this composition root after
        // Poco has performed its initial logging setup. Reconfigure explicitly
        // so formatter/channel changes apply to the server and every OSP bundle.
        Poco::Util::LoggingConfigurator loggingConfigurator;
        loggingConfigurator.configure(configPtr());

        const int requestedCapacity = config().getInt("poco.threadPool.default.capacity", 32);
        const int capacityDelta = requestedCapacity - Poco::ThreadPool::defaultPool().capacity();
        if (capacityDelta > 0)
            Poco::ThreadPool::defaultPool().addCapacity(capacityDelta);

#if defined(PDR_ENABLE_OBSERVABILITY)
        PocoDDS::Observability::MetricsOptions metricsOptions;
        metricsOptions.serviceName = config().getString("observability.metrics.serviceName", "pdr-runtime");
        metricsOptions.serviceInstanceId = config().getString(
            "observability.metrics.serviceInstanceId", Poco::Environment::nodeName());
        if (metricsOptions.serviceInstanceId.empty())
            metricsOptions.serviceInstanceId = Poco::Environment::nodeName();
        metricsOptions.otlpHttpEndpoint = config().getString(
            "observability.metrics.otlpHttpEndpoint", "");
        metricsOptions.otlpCaCertificatePath = config().getString(
            "observability.metrics.otlpCaCertificatePath", "");
        metricsOptions.otlpClientCertificatePath = config().getString(
            "observability.metrics.otlpClientCertificatePath", "");
        metricsOptions.otlpClientKeyPath = config().getString(
            "observability.metrics.otlpClientKeyPath", "");
        metricsOptions.otlpInsecureSkipVerify = config().getBool(
            "observability.metrics.otlpInsecureSkipVerify", false);
        metricsOptions.offlineCachePath = config().getString(
            "observability.metrics.offlineCachePath", "data/metrics/otlp-cache");
        metricsOptions.offlineCacheMaximumFiles = static_cast<std::size_t>(config().getUInt(
            "observability.metrics.offlineCacheMaximumFiles", 1000));
        metricsOptions.exportInterval = std::chrono::milliseconds(config().getInt64(
            "observability.metrics.exportIntervalMilliseconds", 10000));
        metricsOptions.exportTimeout = std::chrono::milliseconds(config().getInt64(
            "observability.metrics.exportTimeoutMilliseconds", 5000));
        metricsOptions.maximumSeries = static_cast<std::size_t>(config().getUInt(
            "observability.metrics.maximumSeries", 2000));
        PocoDDS::Observability::Metrics::global().initialize(std::move(metricsOptions));
        PocoDDS::Protocols::ProtocolMetrics::setSink([](const auto& event) {
            auto& metrics = PocoDDS::Observability::Metrics::global();
            const PocoDDS::Observability::MetricAttributes attributes{
                {"protocol", event.protocol}, {"operation", event.operation},
                {"result", event.result}};
            metrics.addCounter("pdr.protocol.operations", 1, attributes,
                               "Physical protocol operations", "{operation}");
            metrics.recordHistogram("pdr.protocol.operation.duration",
                                    event.durationMilliseconds, attributes,
                                    "Physical protocol operation duration", "ms");
            if (event.bytes)
                metrics.addCounter("pdr.protocol.io", event.bytes,
                                   {{"protocol", event.protocol},
                                    {"operation", event.operation}},
                                   "Physical protocol bytes transferred", "By");
        });
        PocoDDS::Observability::Metrics::global().addCounter(
            "pdr.runtime.starts", 1, {{"host", Poco::Environment::nodeName()}},
            "Runtime process starts", "{start}");
        _traceRuntime = std::make_unique<PocoDDS::FastDDS::Runtime>(
            static_cast<std::uint32_t>(config().getUInt("pdr.fastdds.domainId", 0)),
            "pdr-business-trace-collector");
        _traceRuntime->start();
        _traceRuntime->subscribe(
            "pdr.observability.span", [this](const PocoDDS::FastDDS::Envelope& envelope) {
                try
                {
                    PocoDDS::Observability::globalTraceStore().upsert(
                        PocoDDS::Observability::deserializeSpanSnapshot(envelope.payload));
                }
                catch (const std::exception& exception)
                {
                    logger().warning("Rejected malformed business span: %s",
                                     std::string(exception.what()));
                }
            });
#endif
        ServerApplication::initialize(self);
        if (_showHelp)
            return;

#if defined(PDR_ENABLE_OBSERVABILITY)
        PocoDDS::Observability::BusinessTracerOptions tracingOptions;
        tracingOptions.bundleName = "pdr.runtime";
        tracingOptions.otlpHttpEndpoint =
            config().getString("observability.otlpHttpEndpoint", "");
        PocoDDS::Observability::BusinessTracer startupTracer(
            "pdr-runtime", std::move(tracingOptions));
        auto startupTrace = startupTracer.startBusiness(
            "PocoDDSRuntime启动",
            {{"configuration.count", std::to_string(_configurationFiles.size())}});
        auto bundleStep = startupTrace.startStep("加载OSP Bundles");
#endif
        std::vector<Poco::OSP::Bundle::Ptr> bundles;
        _osp->bundleLoader().listBundles(bundles);
        logger().information("PocoDDSRuntime contains %z loaded bundle(s).", bundles.size());
        for (const auto& bundle : bundles)
        {
            logger().information("OSP bundle: %s/%s state=%d.", bundle->symbolicName(),
                                 bundle->version().toString(), static_cast<int>(bundle->state()));
        }
#if defined(PDR_ENABLE_OBSERVABILITY)
        bundleStep.success({{"bundle.count", std::to_string(bundles.size())}});
        auto readyStep = startupTrace.startStep("运行时就绪");
        readyStep.log("OSP container and administration composition root initialized");
        readyStep.success({{"host", Poco::Environment::nodeName()}});
        startupTrace.success({{"result", "ready"}});
#endif
        logger().information("PocoDDSRuntime server ready on %s (%s), %u CPU core(s).",
                             Poco::Environment::osDisplayName(),
                             Poco::Environment::osArchitecture(),
                             Poco::Environment::processorCount());
    }

    void defineOptions(Poco::Util::OptionSet& options) override
    {
        ServerApplication::defineOptions(options);
        options.addOption(Poco::Util::Option("help", "h", "Display command-line help.")
                              .required(false)
                              .repeatable(false)
                              .callback(Poco::Util::OptionCallback<MacchinaServer>(
                                  this, &MacchinaServer::handleHelp)));
        options.addOption(Poco::Util::Option("config-file", "c", "Load a configuration file.")
                              .required(false)
                              .repeatable(true)
                              .argument("file")
                              .callback(Poco::Util::OptionCallback<MacchinaServer>(
                                  this, &MacchinaServer::handleConfiguration)));
        options.addOption(
            Poco::Util::Option("skip-default-config", "", "Do not load the default config file.")
                .required(false)
                .repeatable(false)
                .callback(Poco::Util::OptionCallback<MacchinaServer>(
                    this, &MacchinaServer::handleSkipDefaultConfig)));
    }

    int main(const std::vector<std::string>&) override
    {
        if (_showHelp)
            return Application::EXIT_OK;

        if (config().getBool("osp.bundleMonitor.enabled", true))
        {
            PocoDDS::BundleManagement::BundleManagerOptions options;
            options.repositories = config().getString(
                "osp.bundleRepository", config().expand("${application.dir}bundles/"));
            options.intervalMilliseconds =
                config().getInt64("osp.bundleMonitor.intervalMilliseconds", 1000);
            _bundleManager = std::make_unique<PocoDDS::BundleManagement::BundleManager>(
                *_osp, logger(), std::move(options));
            _bundleManager->start();
        }

        PocoDDS::ProcessManagement::SubprocessManagerOptions subprocessOptions;
        subprocessOptions.shutdownTimeoutMilliseconds =
            config().getInt64("pdr.subprocess.shutdownTimeoutMilliseconds", 5000);
        _subprocessManager =
            std::make_unique<PocoDDS::ProcessManagement::SubprocessManager>(
                logger(), subprocessOptions);
        const std::string subprocessConfiguration = config().getString(
            "pdr.subprocess.configuration",
            config().expand("${application.dir}pdr-subprocesses.properties"));
        const std::string processRoot = config().expand("${application.dir}");
        const std::size_t startedSubprocesses =
            _subprocessManager->startFromConfiguration(subprocessConfiguration, processRoot);
        logger().information("Started %z configured subprocess(es).", startedSubprocesses);
#if defined(PDR_ENABLE_OBSERVABILITY)
        PocoDDS::Observability::Metrics::global().recordHistogram(
            "pdr.runtime.subprocesses", static_cast<double>(startedSubprocesses), {},
            "Configured subprocesses started by the runtime", "{process}");
#endif
#if defined(PDR_ENABLE_OBSERVABILITY)
        if (startedSubprocesses > 0)
        {
            _traceRuntime->preparePublisher("pdr.process.heartbeat.request");
            _traceRuntime->subscribe(
                "pdr.process.heartbeat.response",
                [this](const PocoDDS::FastDDS::Envelope& envelope) {
                    {
                        std::lock_guard<std::mutex> lock(_heartbeatMutex);
                        _heartbeatResponses.insert(envelope.correlationId);
                    }
                    _heartbeatCondition.notify_all();
                });
            PocoDDS::Observability::BusinessTracerOptions heartbeatOptions;
            heartbeatOptions.bundleName = "pdr.runtime";
            _heartbeatTracer = std::make_unique<PocoDDS::Observability::BusinessTracer>(
                "pdr-runtime-heartbeat", std::move(heartbeatOptions));
            _heartbeatStopping = false;
            _heartbeatThread = std::thread([this] { heartbeatLoop(); });
        }
        else
        {
            logger().information(
                "Internal subprocess transport heartbeat disabled: no subprocess is running.");
        }
#endif

        waitForTerminationRequest();
#if defined(PDR_ENABLE_OBSERVABILITY)
        _heartbeatStopping = true;
        _heartbeatCondition.notify_all();
        if (_heartbeatThread.joinable())
            _heartbeatThread.join();
#endif
        if (_subprocessManager)
            _subprocessManager->stopAll();
        if (_bundleManager)
            _bundleManager->stop();
#if defined(PDR_ENABLE_OBSERVABILITY)
        if (_traceRuntime)
            _traceRuntime->stop();
        PocoDDS::Observability::Metrics::global().addCounter(
            "pdr.runtime.shutdowns", 1, {}, "Runtime clean shutdowns", "{shutdown}");
        PocoDDS::Observability::Metrics::global().forceFlush();
        PocoDDS::Protocols::ProtocolMetrics::setSink({});
        PocoDDS::Observability::Metrics::global().shutdown();
#endif
        return Application::EXIT_OK;
    }

  private:
#if defined(PDR_ENABLE_OBSERVABILITY)
    void heartbeatLoop()
    {
        std::uint64_t sequence = 0;
        {
            std::unique_lock<std::mutex> lock(_heartbeatMutex);
            _heartbeatCondition.wait_for(
                lock, std::chrono::seconds(3), [&] { return _heartbeatStopping.load(); });
        }
        while (!_heartbeatStopping)
        {
            const std::string correlation = "heartbeat-" +
                std::to_string(Poco::Timestamp().epochMicroseconds()) + "-" +
                std::to_string(++sequence);
            auto business = _heartbeatTracer->startBusiness(
                "主子进程Fast-DDS心跳",
                {{"protocol", "Fast-DDS"}, {"interval", "5000ms"},
                 {"target", "all-subprocesses"}},
                correlation);
            {
                auto step = business.startStep(
                    "主进程广播心跳",
                    {{"topic", "pdr.process.heartbeat.request"},
                     {"correlationId", correlation},
                     {"sequence", std::to_string(sequence)}});
                PocoDDS::FastDDS::Envelope request;
                request.sequence = sequence;
                request.timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
                request.kind = "process.heartbeat.request";
                request.operation = "broadcast";
                request.correlationId = correlation;
                request.traceParent = business.traceParent();
                request.businessName = "主子进程Fast-DDS心跳";
                request.businessInstanceId = correlation;
                request.payload = "{\"command\":\"heartbeat\"}";
                _traceRuntime->publish("pdr.process.heartbeat.request", request);
                step.success({{"published", "true"}, {"ddsStatus", "OK"}});
            }

            bool answered = false;
            {
                std::unique_lock<std::mutex> lock(_heartbeatMutex);
                answered = _heartbeatCondition.wait_for(
                    lock, std::chrono::seconds(3), [&] {
                        return _heartbeatStopping ||
                            _heartbeatResponses.erase(correlation) > 0;
                    });
            }
            auto confirmation = business.startStep(
                "主进程确认应答",
                {{"topic", "pdr.process.heartbeat.response"},
                 {"correlationId", correlation},
                 {"timeout", "3000ms"}});
            if (answered && !_heartbeatStopping)
            {
                confirmation.success({{"response", "received"}, {"link", "connected"}});
                business.success({{"link", "connected"}, {"result", "success"}});
            }
            else if (!_heartbeatStopping)
            {
                confirmation.failure("heartbeat_timeout", "子进程在3秒内未应答",
                                     {{"link", "timeout"}});
                business.failure("heartbeat_timeout", "Fast-DDS心跳链路未走通",
                                 {{"link", "timeout"}});
            }

            std::unique_lock<std::mutex> lock(_heartbeatMutex);
            _heartbeatCondition.wait_for(
                lock, std::chrono::seconds(5), [&] { return _heartbeatStopping.load(); });
        }
    }

#endif

    void handleHelp(const std::string&, const std::string&)
    {
        _showHelp = true;
        Poco::Util::HelpFormatter formatter(options());
        formatter.setCommand(commandName());
        formatter.setUsage("OPTIONS");
        formatter.setHeader("PocoDDSRuntime macchina.io bundle and service container.");
        formatter.format(std::cout);
        stopOptionsProcessing();
        _osp->cancelInit();
    }

    void handleConfiguration(const std::string&, const std::string& value)
    {
        _configurationFiles.push_back(value);
    }

    void handleSkipDefaultConfig(const std::string&, const std::string&)
    {
        _skipDefaultConfig = true;
    }

    RuntimeErrorHandler _errorHandler;
    Poco::OSP::OSPSubsystem* _osp;
    std::unique_ptr<PocoDDS::BundleManagement::BundleManager> _bundleManager;
    std::unique_ptr<PocoDDS::ProcessManagement::SubprocessManager> _subprocessManager;
    bool _showHelp{false};
    bool _skipDefaultConfig{false};
    std::vector<std::string> _configurationFiles;
#if defined(PDR_ENABLE_OBSERVABILITY)
    std::unique_ptr<PocoDDS::FastDDS::Runtime> _traceRuntime;
    std::unique_ptr<PocoDDS::Observability::BusinessTracer> _heartbeatTracer;
    std::thread _heartbeatThread;
    std::atomic<bool> _heartbeatStopping{true};
    std::mutex _heartbeatMutex;
    std::condition_variable _heartbeatCondition;
    std::unordered_set<std::string> _heartbeatResponses;
#endif
};
} // namespace

int main(int argc, char** argv)
{
    try
    {
        MacchinaServer application;
        return application.run(argc, argv);
    }
    catch (const Poco::Exception& exception)
    {
        std::cerr << exception.displayText() << std::endl;
        return Poco::Util::Application::EXIT_SOFTWARE;
    }
}
