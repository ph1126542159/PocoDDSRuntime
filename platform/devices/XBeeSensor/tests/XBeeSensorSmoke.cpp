#include "PocoDDS/Devices/XBeeAnalogSensor.h"

#include <cmath>
#include <iostream>

int main()
{
    using Sensor = PocoDDS::Devices::XBeeAnalogSensor;
    Sensor::Options options;
    options.id = "xbee-temperature-1";
    options.sourceAddress = 0x0013A200405291ABULL;
    options.analogChannel = 0;
    options.conversion = Sensor::Conversion::temperatureCelsius;
    options.physicalQuantity = "temperature";
    options.physicalUnit = "degC";
    Sensor sensor(options);

    PocoDDS::Protocols::XBee::IoSample sample;
    sample.sourceAddress = options.sourceAddress;
    sample.analogChannelMask = 0x01;
    sample.analogSamples[0] = 512;

    int updates = 0;
    sensor.setValueHandler([&](double) { ++updates; });
    if (!sensor.ingest(sample) || updates != 1)
        return 1;
    const double expected = (1200.0 * 512.0 / 1023.0 - 500.0) / 10.0;
    if (std::abs(sensor.value() - expected) > 0.0001 ||
        sensor.physicalQuantity() != "temperature" ||
        sensor.physicalUnit() != "degC")
        return 2;

    sample.sourceAddress = 1;
    if (sensor.ingest(sample))
        return 3;

    std::cout << "XBEE_SENSOR_SMOKE_PASS value=" << sensor.value() << '\n';
    return 0;
}
