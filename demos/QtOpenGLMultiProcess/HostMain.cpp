#include <QApplication>
#include <QLabel>
#include <QMainWindow>
#include <QProcess>
#include <QVBoxLayout>
#include <QWindow>

int main(int argc, char* argv[])
{
    QApplication application(argc, argv);
    QMainWindow window;
    auto* central = new QWidget(&window);
    auto* layout = new QVBoxLayout(central);
    auto* status = new QLabel("Starting supervised OpenGL child process...", central);
    layout->addWidget(status);
    window.setCentralWidget(central);

    auto* process = new QProcess(&window);
    QObject::connect(
        process, &QProcess::readyReadStandardOutput,
        [&]()
        {
            const auto nativeId = process->readAllStandardOutput().trimmed().toULongLong();
            if (nativeId == 0)
                return;
            auto* foreignWindow = QWindow::fromWinId(static_cast<WId>(nativeId));
            if (!foreignWindow)
            {
                status->setText("Platform does not support native child-window embedding");
                return;
            }
            layout->addWidget(QWidget::createWindowContainer(foreignWindow, central));
            status->setText("Child process discovered and embedded");
        });
    QObject::connect(&application, &QCoreApplication::aboutToQuit, process,
                     [process]()
                     {
                         process->terminate();
                         if (!process->waitForFinished(3000))
                             process->kill();
                     });
    process->start(QCoreApplication::applicationDirPath() + "/pdr-qt-opengl-child");

    window.resize(1000, 700);
    window.show();
    return application.exec();
}
