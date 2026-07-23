#include "IoT/MobileConnection/MemoryMobileConnectionService.h"

#include <iostream>

int main()
{
    IoT::MobileConnection::MemoryMobileConnectionService service;
    service.setAPN("internet");
    service.enableRadio(true);
    service.connectData();
    if (!service.isRadioEnabled() || !service.isDataConnected() ||
        service.getAPN() != "internet")
    {
        std::cerr << "MobileConnection smoke test failed\n";
        return 1;
    }
    service.disconnectData();
    return service.isDataConnected() ? 1 : 0;
}
