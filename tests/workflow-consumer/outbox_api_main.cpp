#include "PocoDDS/StoreForward/DeliveryProviderService.h"

#include <Poco/AutoPtr.h>

Poco::AutoPtr<PocoDDS::StoreForward::DeliveryProviderService>
makeInstalledDeliveryProvider();

int main()
{
    auto provider = makeInstalledDeliveryProvider();
    PocoDDS::StoreForward::DeliveryRequest request;
    return provider->deliver(request).disposition ==
                   PocoDDS::StoreForward::DeliveryDisposition::acknowledged
               ? 0
               : 1;
}
