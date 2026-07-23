#include "PocoDDS/Devices/LinuxSysfsGpioDevice.h"

#include <fstream>
#include <iostream>

int main()
{
    const auto root = PocoDDS::Filesystem::temp_directory_path() / "pdr-gpio-smoke";
    PocoDDS::Filesystem::remove_all(root);
    PocoDDS::Filesystem::create_directories(root / "gpio17");
    { std::ofstream(root / "gpio17" / "direction") << "in"; }
    { std::ofstream(root / "gpio17" / "value") << "0"; }

    try
    {
        PocoDDS::Devices::LinuxSysfsGpioDevice gpio(
            "gpio-17", 17,
            PocoDDS::Devices::LinuxSysfsGpioDevice::Direction::output,
            root, false);
        gpio.start();
        if (gpio.execute("write", "1") != "1" ||
            gpio.execute("toggle", "") != "0" ||
            gpio.snapshot().state != PocoDDS::Devices::DeviceState::ready)
            return 1;
        gpio.stop();
    }
    catch (...)
    {
        PocoDDS::Filesystem::remove_all(root);
        throw;
    }

    PocoDDS::Filesystem::remove_all(root);
    std::cout << "LINUX_SYSFS_GPIO_SMOKE_PASS pin=17\n";
    return 0;
}
