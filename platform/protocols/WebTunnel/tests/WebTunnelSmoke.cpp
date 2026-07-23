#include "PocoDDS/Protocols/WebTunnel/Service.h"

#include <iostream>

int main()
{
    using PocoDDS::Protocols::WebTunnel::Property;
    const std::vector<Property> properties{
        {"device.id", "demo-1"},
        {"firmware.version", "0.1.0"}};
    if (properties.size() != 2 || properties.front().name != "device.id")
        return 1;
    std::cout << "WEBTUNNEL_PROTOCOL_SMOKE_PASS properties=" << properties.size() << '\n';
    return 0;
}
