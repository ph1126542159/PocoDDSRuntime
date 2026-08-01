#include "PocoDDS/Protocols/WebTunnel/Service.h"
#include "PocoDDS/Protocols/WebTunnel/SimulatedService.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <iostream>
#include <vector>

int main()
{
    using PocoDDS::Protocols::WebTunnel::Property;
    using PocoDDS::Protocols::WebTunnel::SimulatedService;
    using PocoDDS::Protocols::ProtocolMetricEvent;
    using PocoDDS::Protocols::ProtocolMetrics;
    const std::vector<Property> properties{
        {"device.id", "demo-1"},
        {"firmware.version", "0.1.0"}};
    std::vector<ProtocolMetricEvent> events;
    ProtocolMetrics::setSink([&](const auto& event) { events.push_back(event); });
    SimulatedService service;
    service.connect();
    service.updateProperties(properties);
    const auto echoed = service.exchange({1, 2, 3, 4});
    service.disconnect();
    ProtocolMetrics::setSink({});
    if (properties.size() != 2 || properties.front().name != "device.id" ||
        echoed.size() != 4 || service.bytesSent() != 4 || service.bytesReceived() != 4 ||
        events.size() != 4 || events[2].operation != "exchange")
        return 1;
    std::cout << "WEBTUNNEL_PROTOCOL_SMOKE_PASS properties=" << properties.size() << '\n';
    return 0;
}
