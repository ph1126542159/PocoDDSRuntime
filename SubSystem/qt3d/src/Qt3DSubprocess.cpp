#include "PocoDDS/DDS/Runtime.h"
#include "PocoDDS/Observability/BusinessTracer.h"
#include "PocoDDS/Observability/TraceSerialization.h"

#include <Poco/Process.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleLoader.h>
#include <Poco/OSP/OSPSubsystem.h>
#include <Poco/SharedLibrary.h>
#include <Poco/Timestamp.h>
#include <Poco/Util/Application.h>

#include <QGuiApplication>
#include <QTimer>
#include <Qt3DCore/QEntity>
#include <Qt3DCore/QTransform>
#include <Qt3DExtras/QCuboidMesh>
#include <Qt3DExtras/QForwardRenderer>
#include <Qt3DExtras/QPhongMaterial>
#include <Qt3DExtras/Qt3DWindow>
#include <Qt3DRender/QCamera>

#include <chrono>
#include <fstream>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace
{
struct Options
{
    bool selfTest{false};
    std::string traceParent;
    std::string businessId;
    std::string resultFile;
    std::string instance{"qt3d"};
};

std::optional<std::string> optionValue(int argc, char** argv, const std::string& name)
{
    for (int index = 1; index + 1 < argc; ++index)
    {
        if (argv[index] == name)
            return argv[index + 1];
    }
    return std::nullopt;
}

Options parseOptions(int argc, char** argv)
{
    Options options;
    for (int index = 1; index < argc; ++index)
        options.selfTest = options.selfTest || std::string(argv[index]) == "--self-test";
    options.traceParent = optionValue(argc, argv, "--traceparent").value_or("");
    options.businessId = optionValue(argc, argv, "--business-id").value_or("");
    options.resultFile = optionValue(argc, argv, "--result-file").value_or("");
    options.instance = optionValue(argc, argv, "--instance").value_or("qt3d");
    return options;
}

class TracePublisher
{
  public:
    explicit TracePublisher(const Options& options)
        : _options(options), _runtime(0, "pdr-qt3d-" + options.instance)
    {
        _runtime.start();
        _runtime.preparePublisher("pdr.observability.span");
        _runtime.preparePublisher("pdr.process.heartbeat.response");
        PocoDDS::Observability::BusinessTracerOptions heartbeatOptions;
        heartbeatOptions.bundleName = "subsystem.qt3d";
        heartbeatOptions.onChanged =
            [this](const auto& snapshot) { publish(snapshot); };
        _heartbeatTracer = std::make_unique<PocoDDS::Observability::BusinessTracer>(
            "pdr-qt3d-heartbeat", std::move(heartbeatOptions));
        _runtime.subscribe("pdr.process.heartbeat.request",
            [this](const PocoDDS::FastDDS::Envelope& request) {
                auto business = _heartbeatTracer->continueBusiness(
                    "主子进程Fast-DDS心跳", "子进程处理心跳",
                    request.traceParent, request.businessInstanceId,
                    {{"topic", "pdr.process.heartbeat.request"},
                     {"correlationId", request.correlationId},
                     {"sequence", std::to_string(request.sequence)}});
                {
                    auto receive = business.startStep(
                        "子进程收到心跳",
                        {{"command", "heartbeat"},
                         {"source", "pdr-runtime"},
                         {"receivedAt", std::to_string(Poco::Timestamp().epochMicroseconds())}});
                    receive.success({{"accepted", "true"}, {"processId",
                        std::to_string(Poco::Process::id())}});
                }
                PocoDDS::FastDDS::Envelope response;
                response.sequence = request.sequence;
                response.timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
                response.kind = "process.heartbeat.response";
                response.operation = "ack";
                response.correlationId = request.correlationId;
                response.traceParent = business.traceParent();
                response.businessName = request.businessName;
                response.businessInstanceId = request.businessInstanceId;
                response.status = 200;
                response.payload = "{\"ack\":true}";
                {
                    auto reply = business.startStep(
                        "子进程发送应答",
                        {{"topic", "pdr.process.heartbeat.response"},
                         {"correlationId", request.correlationId}});
                    _runtime.publish("pdr.process.heartbeat.response", response);
                    reply.success({{"published", "true"}, {"status", "200"}});
                }
                business.success({{"ack", "true"}, {"link", "connected"}});
            });
    }

    ~TracePublisher() { _runtime.stop(); }

    void publish(const PocoDDS::Observability::SpanSnapshot& snapshot)
    {
        PocoDDS::FastDDS::Envelope envelope;
        envelope.kind = "observability.span";
        envelope.operation = "upsert";
        envelope.payload = PocoDDS::Observability::serializeSpanSnapshot(snapshot);
        envelope.traceParent = snapshot.traceParent;
        envelope.businessName = snapshot.businessName;
        envelope.businessInstanceId = snapshot.businessInstanceId;
        _runtime.publish("pdr.observability.span", envelope);
        _latest = snapshot;
    }

    void writeResult() const
    {
        if (_options.resultFile.empty() || !_latest)
            return;
        std::ofstream output(_options.resultFile, std::ios::trunc);
        output << _latest->traceId << '\n'
               << _latest->processId << '\n'
               << _latest->businessInstanceId << '\n'
               << _latest->status << '\n';
    }

  private:
    Options _options;
    PocoDDS::FastDDS::Runtime _runtime;
    std::unique_ptr<PocoDDS::Observability::BusinessTracer> _heartbeatTracer;
    std::optional<PocoDDS::Observability::SpanSnapshot> _latest;
};

struct Scene
{
    std::unique_ptr<Qt3DCore::QEntity> root{std::make_unique<Qt3DCore::QEntity>()};
    Qt3DCore::QTransform* transform{nullptr};
};

Scene createScene()
{
    Scene scene;
    auto* cube = new Qt3DCore::QEntity(scene.root.get());
    auto* mesh = new Qt3DExtras::QCuboidMesh(cube);
    auto* material = new Qt3DExtras::QPhongMaterial(cube);
    scene.transform = new Qt3DCore::QTransform(cube);
    cube->addComponent(mesh);
    cube->addComponent(material);
    cube->addComponent(scene.transform);
    return scene;
}

void writeProcessStatus(Poco::OSP::OSPSubsystem& osp)
{
    Poco::JSON::Object root;
    root.set("pid", static_cast<unsigned long>(Poco::Process::id()));
    root.set("name", "pdr-qt3d-subprocess");
    root.set("location", "local");
    root.set("state", "running");
    Poco::JSON::Array::Ptr bundles = new Poco::JSON::Array;
    std::vector<Poco::OSP::Bundle::Ptr> loaded;
    osp.bundleLoader().listBundles(loaded);
    for (const auto& item : loaded)
    {
        Poco::JSON::Object::Ptr bundle = new Poco::JSON::Object;
        bundle->set("id", item->symbolicName());
        bundle->set("name", item->name());
        bundle->set("version", item->version().toString());
        bundle->set("state", item->stateString());
        bundles->add(bundle);
    }
    root.set("bundles", bundles);
    root.set("children", Poco::JSON::Array::Ptr(new Poco::JSON::Array));
    std::ofstream output("pdr-process-status.json", std::ios::trunc);
    root.stringify(output, 2);
}

int runQt3D(const Options& options, Poco::OSP::OSPSubsystem& osp,
            int argc, char** argv)
{
    writeProcessStatus(osp);
    if (options.selfTest && qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM"))
        qputenv("QT_QPA_PLATFORM", "offscreen");
    auto application = std::make_unique<QGuiApplication>(argc, argv);
    std::unique_ptr<Qt3DExtras::Qt3DWindow> window;
    if (!options.selfTest)
    {
        window = std::make_unique<Qt3DExtras::Qt3DWindow>();
        window->setTitle(QStringLiteral("PocoDDSRuntime Qt3D Subprocess"));
        window->resize(960, 640);
    }

    TracePublisher publisher(options);
    PocoDDS::Observability::BusinessTracerOptions traceOptions;
    traceOptions.bundleName = "subsystem.qt3d";
    traceOptions.onChanged =
        [&](const auto& snapshot) { publisher.publish(snapshot); };
    PocoDDS::Observability::BusinessTracer tracer(
        "pdr-qt3d-" + options.instance, std::move(traceOptions));

    auto business = options.traceParent.empty()
                        ? tracer.startBusiness(
                              "Qt3D多进程架构测试",
                              {{"instance", options.instance}},
                              options.businessId)
                        : tracer.continueBusiness(
                              "Qt3D多进程架构测试",
                              "Qt3D子进程启动",
                              options.traceParent,
                              options.businessId,
                              {{"instance", options.instance}});

    auto scene = createScene();
    {
        auto step = business.startStep(
            "创建Qt3D场景",
            {{"entity", "cube"}, {"renderer", options.selfTest ? "headless" : "window"}});
        step.log("Qt3D entity/component graph created",
                 "info",
                 {{"pid", std::to_string(Poco::Process::id())}});
        step.success({{"sceneReady", "true"}});
    }

    if (window)
    {
        window->setRootEntity(scene.root.get());
        window->camera()->lens()->setPerspectiveProjection(45.0F, 1.5F, 0.1F, 1000.0F);
        window->camera()->setPosition(QVector3D(0.0F, 0.0F, 10.0F));
        window->camera()->setViewCenter(QVector3D(0.0F, 0.0F, 0.0F));
        window->show();
        auto* timer = new QTimer(application.get());
        QObject::connect(timer, &QTimer::timeout, [transform = scene.transform]() {
            transform->setRotationY(transform->rotationY() + 1.0F);
        });
        timer->start(16);
    }

    business.success({{"processId", std::to_string(Poco::Process::id())},
                      {"sceneReady", "true"}});
    publisher.writeResult();
    std::cout << "QT3D_SUBPROCESS_READY instance=" << options.instance
              << " pid=" << Poco::Process::id() << '\n';

    if (options.selfTest)
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(350));
        return 0;
    }
    return application->exec();
}

class Qt3DContainerApplication final : public Poco::Util::Application
{
public:
    Qt3DContainerApplication(int argc, char** argv, Options options)
        : _options(std::move(options)), _executable(argv[0]),
          _osp(new Poco::OSP::OSPSubsystem)
    {
        (void) argc;
        char* applicationArgv[] = {argv[0], nullptr};
        init(1, applicationArgv);
        addSubsystem(_osp);
    }

protected:
    void initialize(Application& self) override
    {
        Poco::SharedLibrary::setSearchPath(config().getString("application.dir"));
        loadConfiguration();
        Application::initialize(self);
    }

    int main(const std::vector<std::string>&) override
    {
        std::vector<char> executable(_executable.begin(), _executable.end());
        executable.push_back('\0');
        int qtArgc = 1;
        char* qtArgv[] = {executable.data(), nullptr};
        return runQt3D(_options, *_osp, qtArgc, qtArgv);
    }

private:
    Options _options;
    std::string _executable;
    Poco::OSP::OSPSubsystem* _osp;
};
} // namespace

int main(int argc, char** argv)
{
    const Options options = parseOptions(argc, argv);
    try
    {
        Qt3DContainerApplication application(argc, argv, options);
        return application.run();
    }
    catch (const std::exception& exception)
    {
        std::cerr << "QT3D_SUBPROCESS_FAIL " << exception.what() << '\n';
        return 1;
    }
}
