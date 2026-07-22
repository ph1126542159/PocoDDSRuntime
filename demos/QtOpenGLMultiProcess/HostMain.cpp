#include "PocoDDS/Observability/BusinessTracer.h"
#include "PocoDDS/Supervisor/Supervisor.h"
#include "PocoDDS/Transport/FastDDSTransport.h"

#include <QApplication>
#include <QCoreApplication>
#include <QFile>
#include <QHBoxLayout>
#include <QLabel>
#include <QMainWindow>
#include <QMetaObject>
#include <QPushButton>
#include <QTimer>
#include <QVBoxLayout>
#include <QWindow>

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace
{
constexpr const char* SurfaceTopic = "pdr.demo.qt.surface.v1";
constexpr const char* RenderTopic = "pdr.demo.qt.render.v1";
constexpr const char* RenderResultTopic = "pdr.demo.qt.render.result.v1";
constexpr const char* CrashTopic = "pdr.demo.qt.crash.v1";

std::vector<std::byte> payload(const std::string& text)
{
    std::vector<std::byte> result;
    result.reserve(text.size());
    for (const auto value : text)
        result.push_back(std::byte(static_cast<unsigned char>(value)));
    return result;
}

std::string payloadText(const PocoDDS::Transport::Message& message)
{
    return {reinterpret_cast<const char*>(message.payload.data()), message.payload.size()};
}

std::string traceId(const std::string& traceParent)
{
    if (traceParent.size() < 36 || traceParent[2] != '-' || traceParent[35] != '-')
        return {};
    return traceParent.substr(3, 32);
}
} // namespace

int main(int argc, char* argv[])
{
    QApplication application(argc, argv);
    const bool acceptance = argc > 1 && std::string(argv[1]) == "--acceptance";
    const std::string markerPath = acceptance && argc > 2 ? argv[2] : std::string{};
    const auto domainArgument = acceptance ? 3 : 1;
    const auto domain =
        argc > domainArgument ? static_cast<std::uint32_t>(std::stoul(argv[domainArgument])) : 42U;

    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Supervisor::Supervisor supervisor(registry,
                                               PocoDDS::Supervisor::createNativeProcessLauncher());
    supervisor.add({"qt.render.child",
                    PDR_QT_CHILD_PATH,
                    {std::to_string(domain)},
                    QCoreApplication::applicationDirPath().toStdString(),
                    std::chrono::milliseconds(0)},
                   {5, std::chrono::minutes(1)});
    PocoDDS::Transport::FastDDSTransport transport(
        {domain, "qt-opengl-host", PocoDDS::Transport::FastDDSTransportMode::Automatic});
    PocoDDS::Observability::BusinessTracer tracer("qt.opengl.host");

    QMainWindow window;
    auto* central = new QWidget(&window);
    auto* layout = new QVBoxLayout(central);
    auto* status = new QLabel("Starting supervised OpenGL child process...", central);
    auto* controls = new QHBoxLayout;
    auto* render = new QPushButton("发送 DDS 渲染命令", central);
    auto* crash = new QPushButton("注入子进程崩溃并自动重启", central);
    controls->addWidget(render);
    controls->addWidget(crash);
    layout->addWidget(status);
    layout->addLayout(controls);
    window.setCentralWidget(central);

    QWidget* container = nullptr;
    WId currentSurface = 0;
    std::mutex traceMutex;
    std::optional<PocoDDS::Observability::BusinessSpan> pendingSpan;
    std::string pendingTraceId;
    int angle = 0;
    std::atomic<int> firstProcessId{0};
    std::atomic<int> restartedProcessId{0};
    std::atomic<bool> restarted{false};
    std::atomic<bool> firstRenderSent{false};
    std::atomic<bool> crashSent{false};
    std::atomic<bool> secondRenderSent{false};
    std::atomic<int> successfulResults{0};

    auto finishAcceptance = [&](const std::string& result, int exitCode)
    {
        if (!acceptance)
            return;
        QFile marker(QString::fromStdString(markerPath));
        if (marker.open(QIODevice::WriteOnly | QIODevice::Truncate))
        {
            marker.write(result.c_str(), static_cast<qint64>(result.size()));
            marker.close();
        }
        std::cout << result << std::flush;
        application.exit(exitCode);
    };

    registry.observe(
        [&](const PocoDDS::Core::Component& component)
        {
            if (component.id != "qt.render.child" ||
                component.state != PocoDDS::Core::ComponentState::Running)
                return;
            int expected = 0;
            if (firstProcessId.compare_exchange_strong(expected, component.processId))
                return;
            if (component.processId != firstProcessId.load())
            {
                restartedProcessId = component.processId;
                restarted = true;
            }
        });

    auto requestRender = [&]
    {
        angle = (angle + 30) % 360;
        std::lock_guard lock(traceMutex);
        pendingSpan.emplace(tracer.start("request-render", {{"angle", std::to_string(angle)}}));
        pendingTraceId = traceId(pendingSpan->traceParent());
        transport.publish({RenderTopic, "PocoDDS.QtRenderCommand.v1",
                           payload(std::to_string(angle)), pendingSpan->traceParent()});
    };

    auto injectCrash = [&]
    {
        currentSurface = 0;
        transport.publish({CrashTopic, "PocoDDS.QtCrashCommand.v1", {}, {}});
        status->setText("Crash injected; Supervisor is waiting to restart child...");
    };

    auto surfaceSubscription = transport.subscribe(
        SurfaceTopic,
        [&](const auto& message)
        {
            const auto nativeId = static_cast<WId>(std::stoull(payloadText(message)));
            QMetaObject::invokeMethod(
                &window,
                [&, nativeId]
                {
                    if (nativeId == currentSurface)
                        return;
                    currentSurface = nativeId;
                    if (container)
                    {
                        layout->removeWidget(container);
                        container->deleteLater();
                    }
                    auto* foreignWindow = QWindow::fromWinId(nativeId);
                    if (!foreignWindow)
                    {
                        status->setText("Platform does not support native child-window embedding");
                    }
                    else
                    {
                        container = QWidget::createWindowContainer(foreignWindow, central);
                        layout->addWidget(container);
                        status->setText("Child discovered through Fast-DDS and embedded");
                    }
                    if (acceptance && !firstRenderSent.exchange(true))
                        QMetaObject::invokeMethod(&window, requestRender, Qt::QueuedConnection);
                    else if (acceptance && restarted && crashSent &&
                             !secondRenderSent.exchange(true))
                        QMetaObject::invokeMethod(&window, requestRender, Qt::QueuedConnection);
                },
                Qt::QueuedConnection);
        });
    auto resultSubscription = transport.subscribe(
        RenderResultTopic,
        [&](const auto& message)
        {
            bool traceContinuous = false;
            {
                std::lock_guard lock(traceMutex);
                if (pendingSpan)
                {
                    traceContinuous =
                        !pendingTraceId.empty() && pendingTraceId == traceId(message.traceParent);
                    pendingSpan->addLog(traceContinuous ? "child render result received"
                                                        : "child trace context mismatch");
                    pendingSpan->finish(traceContinuous ? "success" : "failure",
                                        {{"result", payloadText(message)}});
                    pendingSpan.reset();
                }
            }
            QMetaObject::invokeMethod(
                status,
                [&, traceContinuous, text = payloadText(message)]
                {
                    status->setText(QString::fromStdString("Trace-complete response: " + text));
                    if (!acceptance)
                        return;
                    if (!traceContinuous)
                    {
                        finishAcceptance("QT_DDS_ACCEPTANCE_FAIL: trace context mismatch\n", 2);
                        return;
                    }
                    const auto count = ++successfulResults;
                    if (count == 1)
                    {
                        crashSent = true;
                        injectCrash();
                    }
                    else if (count == 2 && restarted && secondRenderSent)
                    {
                        finishAcceptance("QT_DDS_TRACE_CRASH_RESTART_PASS\nfirst_pid=" +
                                             std::to_string(firstProcessId.load()) +
                                             "\nrestarted_pid=" +
                                             std::to_string(restartedProcessId.load()) + "\n",
                                         0);
                    }
                },
                Qt::QueuedConnection);
        });

    QObject::connect(render, &QPushButton::clicked, requestRender);
    QObject::connect(crash, &QPushButton::clicked, injectCrash);

    QTimer supervisorPoll;
    QObject::connect(&supervisorPoll, &QTimer::timeout, [&] { supervisor.poll(); });
    supervisorPoll.start(100);
    QObject::connect(&application, &QCoreApplication::aboutToQuit,
                     [&] { supervisor.stop("qt.render.child"); });
    supervisor.start("qt.render.child");

    QTimer acceptanceTimeout;
    if (acceptance)
    {
        acceptanceTimeout.setSingleShot(true);
        QObject::connect(&acceptanceTimeout, &QTimer::timeout,
                         [&] { finishAcceptance("QT_DDS_ACCEPTANCE_FAIL: timeout\n", 3); });
        acceptanceTimeout.start(30000);
    }

    window.resize(1000, 700);
    window.show();
    return application.exec();
}
