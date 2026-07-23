#include "PocoDDS/Protocols/BtLE/GattClient.h"
#include "PocoDDS/Protocols/BtLE/PeripheralBrowser.h"

#include <iostream>

int main()
{
    using namespace PocoDDS::Protocols::BtLE;
    Characteristic characteristic{
        "00002a37-0000-1000-8000-00805f9b34fb",
        10,
        static_cast<std::uint16_t>(Characteristic::Read | Characteristic::Notify),
        11};
    PeripheralInfo peripheral{
        "68:C9:0B:06:23:09",
        "heart-rate",
        -42,
        {"0000180d-0000-1000-8000-00805f9b34fb"}};

    if ((characteristic.properties & Characteristic::Notify) == 0 ||
        characteristic.valueHandle != 11 ||
        peripheral.serviceUuids.size() != 1)
        return 1;

    std::cout << "BTLE_SMOKE_PASS address=" << peripheral.address << " rssi=" << peripheral.rssi << '\n';
    return 0;
}
