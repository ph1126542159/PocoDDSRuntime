#include <PocoDDS/RuntimeCore/InProcessTransport.h>
#include <PocoDDS/TransportProviders/TransportFactoryService.h>

#include <memory>

class ExternalTransportProvider final
    : public PocoDDS::TransportProviders::TransportFactoryService
{
public:
    PocoDDS::RuntimeCore::TransportDescriptor descriptor() const override
    {
        return {"external-sample", "1.0.0",
                {true, false, false, false, false, true}, {}};
    }

    PocoDDS::RuntimeCore::Outcome<
        std::shared_ptr<PocoDDS::RuntimeCore::IMessageTransport>>
    create(const PocoDDS::RuntimeCore::TransportConfiguration&) const override
    {
        return PocoDDS::RuntimeCore::Outcome<
            std::shared_ptr<PocoDDS::RuntimeCore::IMessageTransport>>::success(
            std::make_shared<PocoDDS::RuntimeCore::InProcessTransport>());
    }
};

PocoDDS::TransportProviders::TransportFactoryService* createExternalTransportProvider()
{
    return new ExternalTransportProvider;
}
