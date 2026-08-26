#include "PocoDDS/StoreForward/DeliveryProviderService.h"

class InstalledDeliveryProvider final
    : public PocoDDS::StoreForward::DeliveryProviderService
{
public:
    PocoDDS::StoreForward::ProviderDescriptor descriptor() const override
    {
        return {"installed-delivery", "1.0.0", 4096};
    }

    PocoDDS::StoreForward::DeliveryResult deliver(
        const PocoDDS::StoreForward::DeliveryRequest&) override
    {
        return PocoDDS::StoreForward::DeliveryResult::ack();
    }
};

Poco::AutoPtr<PocoDDS::StoreForward::DeliveryProviderService>
makeInstalledDeliveryProvider()
{
    return new InstalledDeliveryProvider;
}
