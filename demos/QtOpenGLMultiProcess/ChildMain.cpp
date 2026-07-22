#include "PocoDDS/Control/DiscoveryAgent.h"
#include "PocoDDS/Observability/BusinessTracer.h"
#include "PocoDDS/Transport/FastDDSTransport.h"

#include <QApplication>
#include <QMetaObject>
#include <QOpenGLWidget>
#include <QPainter>
#include <QTimer>

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <string>
#include <utility>

namespace
{
constexpr const char* SurfaceTopic = "pdr.demo.qt.surface.v1";
constexpr const char* RenderTopic = "pdr.demo.qt.render.v1";
constexpr const char* RenderResultTopic = "pdr.demo.qt.render.result.v1";
constexpr const char* CrashTopic = "pdr.demo.qt.crash.v1";

std::string payloadText(const PocoDDS::Transport::Message& message)
{
    return {reinterpret_cast<const char*>(message.payload.data()), message.payload.size()};
}

std::vector<std::byte> payload(const std::string& text)
{
    std::vector<std::byte> result;
    result.reserve(text.size());
    for (const auto value : text)
        result.push_back(std::byte(static_cast<unsigned char>(value)));
    return result;
}

class RenderSurface final : public QOpenGLWidget
{
  public:
    void setAngle(int angle)
    {
        _angle = angle;
        update();
    }

  protected:
    void paintGL() override
    {
        QPainter painter(this);
        painter.fillRect(rect(), QColor(12, 18, 30));
        painter.setRenderHint(QPainter::Antialiasing);
        painter.translate(width() / 2.0, height() / 2.0);
        painter.rotate(_angle);
        painter.setBrush(QColor(68, 190, 255));
        painter.setPen(Qt::NoPen);
        painter.drawRoundedRect(QRectF(-110, -110, 220, 220), 24, 24);
        painter.resetTransform();
        painter.setPen(Qt::white);
        painter.drawText(rect(), Qt::AlignBottom | Qt::AlignHCenter,
                         QString("DDS angle: %1°").arg(_angle));
    }

  private:
    int _angle{0};
};
} // namespace

int main(int argc, char* argv[])
{
    QApplication application(argc, argv);
    const auto domain = argc > 1 ? static_cast<std::uint32_t>(std::stoul(argv[1])) : 42U;
    PocoDDS::Transport::FastDDSTransport transport(
        {domain, "qt-opengl-child", PocoDDS::Transport::FastDDSTransportMode::Automatic});
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Control::DiscoveryAgent discovery(transport, registry, "qt-opengl-child-node",
                                               std::chrono::milliseconds(250),
                                               std::chrono::seconds(2));
    discovery.registerLocal({"qt.render.surface",
                             "Qt OpenGL Render Surface",
                             "localhost",
                             0,
                             PocoDDS::Core::ComponentKind::Service,
                             PocoDDS::Core::ComponentState::Running,
                             {}});
    discovery.start();
    PocoDDS::Observability::BusinessTracerOptions tracerOptions;
    tracerOptions.otlpHttpEndpoint = qEnvironmentVariable("PDR_OTLP_ENDPOINT").toStdString();
    PocoDDS::Observability::BusinessTracer tracer("qt.render.surface", std::move(tracerOptions));

    RenderSurface surface;
    surface.setWindowTitle("PocoDDS OpenGL child");
    surface.resize(800, 500);
    surface.show();

    auto renderSubscription = transport.subscribe(
        RenderTopic,
        [&](const auto& message)
        {
            auto span = tracer.start("render-command", {{"angle", payloadText(message)}},
                                     message.traceParent);
            const auto childTraceParent = span.traceParent();
            const auto angle = std::stoi(payloadText(message));
            QMetaObject::invokeMethod(
                &surface, [&surface, angle] { surface.setAngle(angle); }, Qt::QueuedConnection);
            span.addLog("render state queued on Qt GUI thread");
            span.finish("success", {{"frame", "scheduled"}});
            transport.publish({RenderResultTopic, "PocoDDS.QtRenderResult.v1",
                               payload("rendered:" + std::to_string(angle)), childTraceParent});
        });
    auto crashSubscription = transport.subscribe(
        CrashTopic,
        [&](const auto&)
        {
            QMetaObject::invokeMethod(
                &application, [&application] { application.exit(42); }, Qt::QueuedConnection);
        });

    QTimer surfaceAnnouncement;
    QObject::connect(&surfaceAnnouncement, &QTimer::timeout,
                     [&]
                     {
                         transport.publish(
                             {SurfaceTopic,
                              "PocoDDS.QtNativeSurface.v1",
                              payload(std::to_string(static_cast<qulonglong>(surface.winId()))),
                              {}});
                     });
    surfaceAnnouncement.start(250);
    return application.exec();
}
