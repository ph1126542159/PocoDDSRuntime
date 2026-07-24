#include "PocoDDS/DDS/Runtime.h"
#include "PocoDDS/Observability/BusinessTracer.h"
#include "PocoDDS/Observability/TraceSerialization.h"
#include "PocoDDS/ProcessManagement/SubprocessManager.h"

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
#include <atomic>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <string>
#include <thread>
#include <utility>
#include <vector>
#include <unordered_map>

namespace
{
struct Options
{
    bool selfTest{false};
    bool windowWorker{false};
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
    {
        options.selfTest = options.selfTest || std::string(argv[index]) == "--self-test";
        options.windowWorker =
            options.windowWorker || std::string(argv[index]) == "--window-worker";
    }
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
        PocoDDS::Observability::BusinessTracerOptions workflowOptions;
        workflowOptions.bundleName =
            options.windowWorker ? "subsystem.qt3d.window" : "subsystem.qt3d.coordinator";
        workflowOptions.onChanged =
            [this](const auto& snapshot) { publish(snapshot); };
        _workflowTracer = std::make_unique<PocoDDS::Observability::BusinessTracer>(
            "pdr-qt3d-" + options.instance, std::move(workflowOptions));

        if (options.windowWorker)
        {
            _runtime.preparePublisher("pdr.qt3d.window.response");
            _runtime.subscribe("pdr.qt3d.window.command",
                [this](const PocoDDS::FastDDS::Envelope& request) {
                    if (request.deviceId != _options.instance)
                        return;
                    handleWindowCommand(request);
                });
            return;
        }

        _runtime.preparePublisher("pdr.qt3d.workflow.response");
        _runtime.preparePublisher("pdr.qt3d.window.command");
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
                // Reuse the proven runtime heartbeat trace as the parent of a
                // realistic Qt3D coordinator -> window worker fan-out.
                auto workflowRequest = request;
                workflowRequest.kind = "qt3d.workflow.request";
                workflowRequest.operation =
                    request.sequence % 3 == 0 ? "simulate-failure" : "simulate-success";
                workflowRequest.businessName = "Qt3D多窗口协同业务";
                workflowRequest.traceParent = business.traceParent();
                workflowRequest.payload = "{\"command\":\"render-all-windows\"}";
                handleWorkflowRequest(workflowRequest);
                business.success({{"ack", "true"}, {"link", "connected"}});
            });
        _runtime.subscribe("pdr.qt3d.workflow.request",
            [this](const PocoDDS::FastDDS::Envelope& request) {
                handleWorkflowRequest(request);
            });
        _runtime.subscribe("pdr.qt3d.window.response",
            [this](const PocoDDS::FastDDS::Envelope& response) {
                handleWindowResponse(response);
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
    struct Workflow
    {
        std::unique_ptr<PocoDDS::Observability::BusinessSpan> business;
        std::set<std::string> responders;
        bool failed{false};
        std::uint64_t sequence{0};
    };

    static const std::vector<std::string>& workerIds()
    {
        static const std::vector<std::string> ids{
            "window-scene", "window-material", "window-device"};
        return ids;
    }

    void handleWorkflowRequest(const PocoDDS::FastDDS::Envelope& request)
    {
        auto business = _workflowTracer->continueBusiness(
            "Qt3D多窗口协同业务", "Qt3D父进程编排",
            request.traceParent, request.businessInstanceId,
            {{"correlationId", request.correlationId},
             {"mode", request.operation},
             {"windowCount", std::to_string(workerIds().size())}});
        const std::string parentTrace = business.traceParent();
        {
            std::lock_guard<std::mutex> lock(_workflowMutex);
            Workflow workflow;
            workflow.business =
                std::make_unique<PocoDDS::Observability::BusinessSpan>(std::move(business));
            workflow.sequence = request.sequence;
            _workflows[request.correlationId] = std::move(workflow);
        }

        auto dispatch = [&]() {
            std::lock_guard<std::mutex> lock(_workflowMutex);
            return _workflows.at(request.correlationId).business->startStep(
                "并行分发窗口任务",
                {{"fanOut", "3"}, {"transport", "Fast-DDS"}});
        }();
        for (const auto& worker : workerIds())
        {
            PocoDDS::FastDDS::Envelope command;
            command.sequence = request.sequence;
            command.timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
            command.kind = "qt3d.window.command";
            command.deviceId = worker;
            command.operation = request.operation;
            command.correlationId = request.correlationId;
            command.traceParent = parentTrace;
            command.businessName = request.businessName;
            command.businessInstanceId = request.businessInstanceId;
            command.payload = "{\"task\":\"render-fragment\"}";
            _runtime.publish("pdr.qt3d.window.command", command);
        }
        dispatch.success({{"published", "3"}, {"targets", "scene,material,device"}});
    }

    void handleWindowCommand(const PocoDDS::FastDDS::Envelope& request)
    {
        auto business = _workflowTracer->continueBusiness(
            "Qt3D多窗口协同业务", "窗口任务-" + _options.instance,
            request.traceParent, request.businessInstanceId,
            {{"window", _options.instance},
             {"correlationId", request.correlationId},
             {"mode", request.operation}});
        {
            auto prepare = business.startStep(
                "窗口准备局部场景",
                {{"window", _options.instance}, {"thread", "Qt-GUI"}});
            prepare.log("Window worker accepted its targeted Fast-DDS command");
            prepare.success({{"ready", "true"},
                             {"pid", std::to_string(Poco::Process::id())}});
        }

        const bool forcedFailure =
            request.operation == "simulate-failure" && _options.instance == "window-device";
        if (_options.instance == "window-material")
        {
            auto retry = business.startStep("材质缓存未命中后降级");
            retry.log("Texture cache miss; using generated checkerboard", "warning");
            retry.success({{"fallback", "checkerboard"}, {"degraded", "true"}});
        }
        else
        {
            auto render = business.startStep(
                "执行窗口局部渲染",
                {{"viewport", _options.instance}, {"drawCalls", "4"}});
            if (forcedFailure)
                render.failure("WINDOW_DEVICE_TIMEOUT",
                               "device overlay did not receive telemetry in time",
                               {{"retryable", "true"}});
            else
                render.success({{"frameReady", "true"}, {"gpuMilliseconds", "2.4"}});
        }

        PocoDDS::FastDDS::Envelope response;
        response.sequence = request.sequence;
        response.timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
        response.kind = "qt3d.window.response";
        response.deviceId = _options.instance;
        response.operation = "window-complete";
        response.correlationId = request.correlationId;
        response.traceParent = business.traceParent();
        response.businessName = request.businessName;
        response.businessInstanceId = request.businessInstanceId;
        response.status = forcedFailure ? 500 : 200;
        response.payload = forcedFailure ? "{\"result\":\"failed\"}" :
                                           "{\"result\":\"success\"}";
        _runtime.publish("pdr.qt3d.window.response", response);
        if (forcedFailure)
            business.failure("WINDOW_BRANCH_FAILED",
                             "window-device branch failed",
                             {{"reported", "true"}});
        else
            business.success({{"result", "completed"}, {"reported", "true"}});
    }

    void handleWindowResponse(const PocoDDS::FastDDS::Envelope& response)
    {
        PocoDDS::FastDDS::Envelope completion;
        bool complete = false;
        {
            std::lock_guard<std::mutex> lock(_workflowMutex);
            const auto iterator = _workflows.find(response.correlationId);
            if (iterator == _workflows.end() ||
                !iterator->second.responders.insert(response.deviceId).second)
                return;
            auto collect = iterator->second.business->startStep(
                "汇聚窗口结果-" + response.deviceId,
                {{"window", response.deviceId},
                 {"status", std::to_string(response.status)}});
            if (response.status >= 400)
            {
                iterator->second.failed = true;
                collect.failure("WINDOW_RESULT_FAILED",
                                response.deviceId + " returned an error");
            }
            else
                collect.success({{"accepted", "true"}});

            if (iterator->second.responders.size() == workerIds().size())
            {
                if (iterator->second.failed)
                {
                    auto compensate =
                        iterator->second.business->startStep("执行跨窗口补偿");
                    compensate.log("Keeping successful windows and marking stale overlay",
                                   "warning");
                    compensate.success({{"strategy", "partial-commit"}});
                    iterator->second.business->failure(
                        "MULTI_WINDOW_PARTIAL_FAILURE",
                        "one or more window branches failed",
                        {{"completed", "3"}, {"compensated", "true"}});
                }
                else
                    iterator->second.business->success(
                        {{"completed", "3"}, {"result", "all-windows-ready"}});

                completion.sequence = iterator->second.sequence;
                completion.timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
                completion.kind = "qt3d.workflow.response";
                completion.operation = "aggregate-complete";
                completion.correlationId = response.correlationId;
                completion.traceParent = iterator->second.business->traceParent();
                completion.businessName = response.businessName;
                completion.businessInstanceId = response.businessInstanceId;
                completion.status = iterator->second.failed ? 500 : 200;
                completion.payload = iterator->second.failed ?
                    "{\"result\":\"partial-failure\"}" :
                    "{\"result\":\"all-windows-ready\"}";
                _workflows.erase(iterator);
                complete = true;
            }
        }
        if (complete)
            _runtime.publish("pdr.qt3d.workflow.response", completion);
    }

    Options _options;
    PocoDDS::FastDDS::Runtime _runtime;
    std::unique_ptr<PocoDDS::Observability::BusinessTracer> _heartbeatTracer;
    std::unique_ptr<PocoDDS::Observability::BusinessTracer> _workflowTracer;
    std::mutex _workflowMutex;
    std::unordered_map<std::string, Workflow> _workflows;
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

std::string nextBusinessId(const std::string& scenario)
{
    static std::atomic<unsigned long> sequence{0};
    return "qt3d-" + scenario + "-" + std::to_string(Poco::Process::id()) + "-" +
        std::to_string(++sequence);
}

void emitSuccessfulFrameFlow(PocoDDS::Observability::BusinessTracer& tracer)
{
    auto business = tracer.startBusiness(
        "Qt3D帧渲染流程",
        {{"scene", "rotating-cube"}, {"quality", "high"}},
        nextBusinessId("frame-success"));
    {
        auto step = business.startStep(
            "更新场景图", {{"entityCount", "2"}, {"frameNumber", "120"}});
        step.log("Transform and camera matrices updated");
        step.success({{"dirtyNodes", "1"}, {"updateMicroseconds", "84"}});
    }
    {
        auto step = business.startStep(
            "提交GPU渲染", {{"backend", "RHI"}, {"drawCalls", "1"}});
        step.log("Render command buffer submitted", "debug");
        step.success({{"gpuMilliseconds", "1.7"}, {"presented", "true"}});
    }
    business.success({{"result", "presented"}, {"frameTimeMilliseconds", "8.3"}});
}

void emitFallbackFlow(PocoDDS::Observability::BusinessTracer& tracer)
{
    auto business = tracer.startBusiness(
        "Qt3D模型资源加载",
        {{"asset", "models/plant.glb"}, {"fallbackEnabled", "true"}},
        nextBusinessId("asset-fallback"));
    {
        auto step = business.startStep("读取外部模型", {{"format", "glTF"}});
        step.log("Model file was not found in the deployment package", "warning");
        step.failure("QT3D_ASSET_NOT_FOUND",
                     "models/plant.glb does not exist",
                     {{"retryable", "false"}});
    }
    {
        auto step = business.startStep(
            "加载内置降级模型", {{"fallback", "QCuboidMesh"}});
        step.log("Using built-in cube to keep the scene available");
        step.success({{"mesh", "cube"}, {"material", "phong"}});
    }
    business.success({{"result", "degraded"}, {"sceneAvailable", "true"}});
}

void emitRetryFlow(PocoDDS::Observability::BusinessTracer& tracer)
{
    auto business = tracer.startBusiness(
        "Qt3D渲染提交重试",
        {{"maximumAttempts", "2"}, {"backend", "RHI"}},
        nextBusinessId("render-retry"));
    {
        auto step = business.startStep("第一次提交", {{"attempt", "1"}});
        step.log("Transient swap-chain contention detected", "warning");
        step.failure("QT3D_SWAPCHAIN_BUSY",
                     "swap chain was temporarily unavailable",
                     {{"willRetry", "true"}});
    }
    {
        auto step = business.startStep(
            "等待退避", {{"delayMilliseconds", "20"}});
        step.success({{"elapsedMilliseconds", "20"}});
    }
    {
        auto step = business.startStep("第二次提交", {{"attempt", "2"}});
        step.log("Render submission recovered after retry");
        step.success({{"presented", "true"}});
    }
    business.success({{"result", "recovered"}, {"attempts", "2"}});
}

void emitFailedDeviceFlow(PocoDDS::Observability::BusinessTracer& tracer)
{
    auto business = tracer.startBusiness(
        "Qt3D设备姿态同步",
        {{"deviceId", "simulated-arm-01"}, {"timeoutMilliseconds", "500"}},
        nextBusinessId("device-failure"));
    {
        auto step = business.startStep(
            "校验姿态指令", {{"jointCount", "6"}, {"coordinateSystem", "world"}});
        step.success({{"valid", "true"}});
    }
    {
        auto step = business.startStep(
            "发送DDS姿态请求", {{"topic", "device.pose.command"}});
        step.log("No device acknowledgement received before deadline", "error");
        step.failure("DDS_REQUEST_TIMEOUT",
                     "simulated-arm-01 did not acknowledge the pose command",
                     {{"elapsedMilliseconds", "500"}});
    }
    {
        auto step = business.startStep("执行状态补偿");
        step.log("Scene pose restored to last confirmed device state", "warning");
        step.success({{"rollback", "completed"}});
    }
    business.failure("DEVICE_POSE_SYNC_FAILED",
                     "device pose could not be synchronized",
                     {{"compensated", "true"}, {"sceneConsistent", "true"}});
}

void emitComplexBusinessScenarios(PocoDDS::Observability::BusinessTracer& tracer)
{
    emitSuccessfulFrameFlow(tracer);
    emitFallbackFlow(tracer);
    emitRetryFlow(tracer);
    emitFailedDeviceFlow(tracer);
}

void writeProcessStatus(
    Poco::OSP::OSPSubsystem& osp,
    const PocoDDS::ProcessManagement::SubprocessManager* manager)
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
    Poco::JSON::Array::Ptr children = new Poco::JSON::Array;
    if (manager)
    {
        for (const auto& info : manager->processes())
        {
            Poco::JSON::Object::Ptr child = new Poco::JSON::Object;
            child->set("id", info.name);
            child->set("name", info.name);
            child->set("pid", info.processId);
            child->set("state", info.state);
            child->set("location", info.location);
            child->set("manageable", info.manageable);
            children->add(child);
        }
    }
    root.set("children", children);
    std::ofstream output("pdr-process-status.json", std::ios::trunc);
    root.stringify(output, 2);
}

int runQt3D(const Options& options, Poco::OSP::OSPSubsystem& osp,
            int argc, char** argv)
{
    std::unique_ptr<PocoDDS::ProcessManagement::SubprocessManager> windowManager;
    if (!options.windowWorker && !options.selfTest)
    {
        windowManager =
            std::make_unique<PocoDDS::ProcessManagement::SubprocessManager>(
                Poco::Util::Application::instance().logger());
        windowManager->startFromConfiguration(
            "pdr-window-subprocesses.properties", ".");
    }
    writeProcessStatus(osp, windowManager.get());
    if (options.selfTest && qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM"))
        qputenv("QT_QPA_PLATFORM", "offscreen");
    auto application = std::make_unique<QGuiApplication>(argc, argv);
    std::unique_ptr<Qt3DExtras::Qt3DWindow> window;
    if (!options.selfTest)
    {
        window = std::make_unique<Qt3DExtras::Qt3DWindow>();
        window->setTitle(
            QString::fromStdString(options.windowWorker ?
                "Qt3D Worker - " + options.instance :
                "PocoDDSRuntime Qt3D Coordinator"));
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
    emitComplexBusinessScenarios(tracer);
    std::cout << "QT3D_SUBPROCESS_READY instance=" << options.instance
              << " pid=" << Poco::Process::id() << '\n';

    if (options.selfTest)
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(350));
        return 0;
    }
    auto* scenarioTimer = new QTimer(application.get());
    QObject::connect(scenarioTimer, &QTimer::timeout,
                     [&tracer]() { emitComplexBusinessScenarios(tracer); });
    scenarioTimer->start(15000);
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
