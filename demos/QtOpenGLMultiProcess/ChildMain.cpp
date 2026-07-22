#include <QApplication>
#include <QOpenGLWidget>
#include <QPainter>
#include <QTextStream>
#include <QTimer>

class RenderSurface final : public QOpenGLWidget
{
  protected:
    void paintGL() override
    {
        QPainter painter(this);
        painter.fillRect(rect(), QColor(12, 18, 30));
        painter.setPen(QColor(68, 190, 255));
        painter.drawText(rect(), Qt::AlignCenter, "PocoDDS child OpenGL process");
    }
};

int main(int argc, char* argv[])
{
    QApplication application(argc, argv);
    RenderSurface surface;
    surface.setWindowTitle("PocoDDS OpenGL child");
    surface.resize(800, 500);
    surface.show();
    QTimer::singleShot(
        0, [&surface]()
        { QTextStream(stdout) << static_cast<qulonglong>(surface.winId()) << Qt::endl; });
    return application.exec();
}
