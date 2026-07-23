#include "IoT/NetworkEnvironment/NetworkEnvironmentServiceImpl.h"

#include <iostream>

int main()
{
    IoT::NetworkEnvironment::NetworkEnvironmentServiceImpl service;
    const auto interfaces = service.enumerateInterfaces(
        IoT::NetworkEnvironment::OPTION_INCLUDE_DOWN |
        IoT::NetworkEnvironment::OPTION_INCLUDE_NON_IP);
    if (interfaces.empty())
    {
        std::cerr << "No network interfaces were enumerated\n";
        return 1;
    }
    return 0;
}
