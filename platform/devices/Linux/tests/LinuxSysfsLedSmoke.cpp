#include "PocoDDS/Devices/LinuxSysfsLedDevice.h"

#include <cmath>
#include <fstream>
#include <iostream>

int main()
{
    const auto root = PocoDDS::Filesystem::temp_directory_path() / "pdr-led-smoke";
    PocoDDS::Filesystem::remove_all(root);
    PocoDDS::Filesystem::create_directories(root);
    { std::ofstream(root / "max_brightness") << "255"; }
    { std::ofstream(root / "brightness") << "0"; }
    PocoDDS::Devices::LinuxSysfsLedDevice led("status-led", root);
    led.start();
    led.setBrightness(0.5);
    if (std::abs(led.brightness() - 128.0 / 255.0) > 0.0001)
        return 1;
    if (led.execute("off", "") != "0.000")
        return 2;
    led.stop();
    PocoDDS::Filesystem::remove_all(root);
    std::cout << "LINUX_SYSFS_LED_SMOKE_PASS\n";
    return 0;
}
