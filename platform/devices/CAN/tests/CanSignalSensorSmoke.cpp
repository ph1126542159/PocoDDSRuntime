#include "PocoDDS/Devices/CanSignalSensor.h"

#include <cmath>
#include <iostream>

int main()
{
    using Sensor = PocoDDS::Devices::CanSignalSensor;
    Sensor::Options options;
    options.id = "engine-temperature";
    options.frameId = 0x123;
    options.bitOffset = 8;
    options.bitLength = 16;
    options.factor = 0.1;
    options.offset = -40;
    options.physicalQuantity = "temperature";
    options.physicalUnit = "degC";
    Sensor sensor(options);

    PocoDDS::Protocols::CAN::CanFrame frame;
    frame.id = 0x123;
    frame.length = 4;
    frame.data = {0x00, 0xD2, 0x04}; // Intel 0x04D2 = 1234
    if (!sensor.ingest(frame) || std::abs(sensor.value() - 83.4) > 0.0001)
        return 1;
    frame.id = 0x124;
    if (sensor.ingest(frame))
        return 2;
    std::cout << "CAN_SIGNAL_SENSOR_SMOKE_PASS value=" << sensor.value() << '\n';
    return 0;
}
