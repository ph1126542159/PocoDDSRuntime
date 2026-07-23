#include "PocoDDS/Devices/NmeaGnssDevice.h"

#include <cmath>
#include <iostream>

int main()
{
    PocoDDS::Devices::NmeaGnssDevice device("gnss-test");
    int updates = 0;
    device.setPositionHandler([&](const auto&) { ++updates; });

    if (!device.ingestSentence(
            "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"))
        return 1;
    if (!device.ingestSentence(
            "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"))
        return 2;
    if (device.ingestSentence(
            "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*00"))
        return 3;

    const auto position = device.position();
    if (!device.hasFix() ||
        std::abs(position.latitude - 48.1173) > 0.00001 ||
        std::abs(position.longitude - 11.5166667) > 0.00001 ||
        std::abs(position.altitude - 545.4) > 0.001 ||
        updates != 2)
        return 4;

    std::cout << "NMEA_GNSS_DEVICE_SMOKE_PASS lat=" << position.latitude
              << " lon=" << position.longitude
              << " altitude=" << position.altitude << '\n';
    return 0;
}
