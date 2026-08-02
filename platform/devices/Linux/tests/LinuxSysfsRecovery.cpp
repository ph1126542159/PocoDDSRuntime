#include "PocoDDS/Devices/LinuxSysfsGpioDevice.h"
#include "PocoDDS/Devices/LinuxSysfsLedDevice.h"

#include <fstream>
#include <stdexcept>
#include <thread>

namespace
{
void writeFile(const PocoDDS::Filesystem::path& path, const std::string& value)
{
    std::ofstream stream(path, std::ios::trunc);
    stream << value;
    if (!stream) throw std::runtime_error("cannot create fixture: " + path.string());
}
}

int main()
{
    const auto root = PocoDDS::Filesystem::temp_directory_path() /
        "pdr-linux-sysfs-recovery";
    PocoDDS::Filesystem::remove_all(root);
    PocoDDS::Filesystem::create_directories(root / "gpio23");
    writeFile(root / "export", "");
    writeFile(root / "unexport", "untouched");
    writeFile(root / "gpio23" / "direction", "in");
    writeFile(root / "gpio23" / "value", "0");

    PocoDDS::Devices::LinuxSysfsGpioDevice gpio(
        "gpio-23", 23,
        PocoDDS::Devices::LinuxSysfsGpioDevice::Direction::output,
        root, true, std::chrono::milliseconds(50));
    gpio.setValueHandler([](std::uint32_t) { throw std::runtime_error("consumer failure"); });
    gpio.start();
    gpio.write(1);
    if (gpio.snapshot().state != PocoDDS::Devices::DeviceState::ready) return 1;
    PocoDDS::Filesystem::remove(root / "gpio23" / "value");
    if (gpio.snapshot().state != PocoDDS::Devices::DeviceState::fault) return 2;
    const auto gpioFailure = gpio.diagnostics();
    const auto gpioStructuredFailure = gpio.failure();
    if (gpioFailure.lastError != "cannot read GPIO value" ||
        gpioStructuredFailure.code != "PDR-DEVICE-LINUX-GPIO_IO_FAILED" ||
        !gpioStructuredFailure.active) return 3;
    writeFile(root / "gpio23" / "value", "0");
    if (gpio.read() != 0 || gpio.snapshot().state != PocoDDS::Devices::DeviceState::ready)
        return 4;
    if (gpio.failure().active) return 12;
    gpio.stop();
    std::string unexportValue;
    { std::ifstream(root / "unexport") >> unexportValue; }
    if (unexportValue != "untouched") return 5;
    if (gpio.snapshot().state != PocoDDS::Devices::DeviceState::offline) return 6;

    const auto ownedRoot = root / "owned";
    PocoDDS::Filesystem::create_directories(ownedRoot);
    writeFile(ownedRoot / "export", "");
    writeFile(ownedRoot / "unexport", "");
    std::thread kernelSimulation([&] {
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
        PocoDDS::Filesystem::create_directories(ownedRoot / "gpio24");
        writeFile(ownedRoot / "gpio24" / "direction", "in");
        writeFile(ownedRoot / "gpio24" / "value", "0");
    });
    PocoDDS::Devices::LinuxSysfsGpioDevice owned(
        "gpio-24", 24,
        PocoDDS::Devices::LinuxSysfsGpioDevice::Direction::input,
        ownedRoot, true, std::chrono::milliseconds(500));
    try { owned.start(); }
    catch (...)
    {
        kernelSimulation.join();
        throw;
    }
    kernelSimulation.join();
    owned.stop();
    std::string exported;
    std::string unexported;
    { std::ifstream(ownedRoot / "export") >> exported; }
    { std::ifstream(ownedRoot / "unexport") >> unexported; }
    if (exported != "24" || unexported != "24") return 7;

    const auto ledRoot = root / "led";
    PocoDDS::Filesystem::create_directories(ledRoot);
    writeFile(ledRoot / "max_brightness", "255");
    writeFile(ledRoot / "brightness", "0");
    PocoDDS::Devices::LinuxSysfsLedDevice led("led-recovery", ledRoot);
    led.setSnapshotHandler([](const auto&) { throw std::runtime_error("consumer failure"); });
    led.start();
    led.setBrightness(0.5);
    PocoDDS::Filesystem::remove(ledRoot / "brightness");
    if (led.snapshot().state != PocoDDS::Devices::DeviceState::fault) return 8;
    const auto ledFailure = led.diagnostics();
    const auto ledStructuredFailure = led.failure();
    if (ledFailure.lastError != "cannot read LED brightness" ||
        ledStructuredFailure.code != "PDR-DEVICE-LINUX-LED_IO_FAILED" ||
        !ledStructuredFailure.active) return 9;
    writeFile(ledRoot / "brightness", "255");
    if (led.brightness() != 1.0 ||
        led.snapshot().state != PocoDDS::Devices::DeviceState::ready) return 10;
    led.stop();
    if (led.snapshot().state != PocoDDS::Devices::DeviceState::offline) return 11;

    PocoDDS::Filesystem::remove_all(root);
    return 0;
}
