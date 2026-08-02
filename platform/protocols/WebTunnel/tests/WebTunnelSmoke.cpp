#include "PocoDDS/Protocols/WebTunnel/Service.h"
#include "PocoDDS/Protocols/WebTunnel/SimulatedService.h"
#include "PocoDDS/Protocols/WebTunnel/LocalForwarder.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <iostream>
#include <stdexcept>
#include <vector>

int main()
{
    using PocoDDS::Protocols::WebTunnel::LocalForwarder;
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
    service.setConnectionHandler([](bool) {
        throw std::runtime_error("consumer failure");
    });
    service.connect();
    service.updateProperties(properties);
    const auto echoed = service.exchange({1, 2, 3, 4});
    service.disconnect();
    ProtocolMetrics::setSink({});
    int rejectedConfigurations = 0;
    const auto rejects = [&](LocalForwarder::Options options) {
        try { LocalForwarder ignored(std::move(options)); }
        catch (const std::invalid_argument&) { ++rejectedConfigurations; }
    };
    rejects({});
    LocalForwarder::Options cleartextTls;
    cleartextTls.remoteUri = "ws://127.0.0.1:9000/tunnel";
    cleartextTls.remotePort = 9080;
    cleartextTls.trustStore = "ca.pem";
    rejects(std::move(cleartextTls));
    LocalForwarder::Options incompleteMtls;
    incompleteMtls.remoteUri = "wss://tunnel.example.com/tunnel";
    incompleteMtls.remotePort = 9080;
    incompleteMtls.clientCertificate = "client.pem";
    rejects(std::move(incompleteMtls));

    if (properties.size() != 2 || properties.front().name != "device.id" ||
        echoed.size() != 4 || service.bytesSent() != 4 || service.bytesReceived() != 4 ||
        service.connectionHandlerFailures() != 2 ||
        events.size() != 4 || events[2].operation != "exchange" ||
        rejectedConfigurations != 3)
        return 1;
    std::cout << "WEBTUNNEL_PROTOCOL_SMOKE_PASS properties=" << properties.size() << '\n';
    return 0;
}
