#include "PocoDDS/Devices/BooleanSensor.h"
#include "PocoDDS/Devices/Counter.h"
#include "PocoDDS/Devices/DigitalIO.h"
#include "PocoDDS/Devices/GNSSSensor.h"
#include "PocoDDS/Devices/MediaDevices.h"
#include "PocoDDS/Devices/MotionSensors.h"
#include "PocoDDS/Devices/Sensor.h"
#include "PocoDDS/Devices/SerialDevice.h"

#include <iostream>
#include <type_traits>

int main()
{
    using namespace PocoDDS::Devices;
    static_assert(std::is_base_of_v<Device, Sensor>);
    static_assert(std::is_base_of_v<Device, BooleanSensor>);
    static_assert(std::is_base_of_v<Device, Counter>);
    static_assert(std::is_base_of_v<Device, GNSSSensor>);
    static_assert(std::is_base_of_v<Device, Accelerometer>);
    static_assert(std::is_base_of_v<Device, Gyroscope>);
    static_assert(std::is_base_of_v<Device, Magnetometer>);
    static_assert(std::is_base_of_v<Device, DigitalIO>);
    static_assert(std::is_base_of_v<Device, LED>);
    static_assert(std::is_base_of_v<Device, Switch>);
    static_assert(std::is_base_of_v<Device, Trigger>);
    static_assert(std::is_base_of_v<Device, Camera>);
    static_assert(std::is_base_of_v<Device, BarcodeReader>);
    static_assert(std::is_base_of_v<Device, RotaryEncoder>);
    static_assert(std::is_base_of_v<Device, SerialDevice>);
    std::cout << "DEVICE_INTERFACES_SMOKE_PASS interfaces=15 remoting=0\n";
    return 0;
}
