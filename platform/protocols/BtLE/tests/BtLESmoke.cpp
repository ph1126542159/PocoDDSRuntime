#include "PocoDDS/Protocols/BtLE/GattClient.h"
#include "PocoDDS/Protocols/BtLE/PeripheralBrowser.h"
#include "PocoDDS/Protocols/BtLE/SimulatedGattClient.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <iostream>
#include <vector>

int main()
{
    using namespace PocoDDS::Protocols::BtLE;
    using PocoDDS::Protocols::ProtocolMetricEvent;
    using PocoDDS::Protocols::ProtocolMetrics;
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

    std::vector<ProtocolMetricEvent> events;
    ProtocolMetrics::setSink([&](const auto& event) { events.push_back(event); });
    SimulatedGattClient client;
    bool notified = false;
    client.setNotificationHandler([&](const ValueEvent& event) { notified = event.data.size() == 3; });
    client.connect(peripheral.address);
    const auto initial = client.read(11);
    client.write(11, {1, 2, 3});
    client.disconnect();
    ProtocolMetrics::setSink({});
    if ((characteristic.properties & Characteristic::Notify) == 0 ||
        characteristic.valueHandle != 11 ||
        peripheral.serviceUuids.size() != 1 || initial.size() != 2 || !notified ||
        events.size() != 4 || events[2].bytes != 3)
        return 1;

    std::cout << "BTLE_SMOKE_PASS address=" << peripheral.address << " rssi=" << peripheral.rssi << '\n';
    return 0;
}
