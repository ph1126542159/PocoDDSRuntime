#include <PocoDDS/TransportProviders/ProviderRegistration.h>

#include <Poco/AutoPtr.h>

#include <iostream>
#include <utility>

PocoDDS::TransportProviders::TransportFactoryService* createExternalTransportProvider();

int main()
{
    PocoDDS::RuntimeCore::TransportRegistry registry;
    Poco::AutoPtr<PocoDDS::TransportProviders::TransportFactoryService> provider =
        createExternalTransportProvider();
    auto attached = PocoDDS::TransportProviders::registerTransportProvider(registry, provider);
    if (!attached) return 1;
    auto registration = std::move(attached).value();
    const auto created = registry.create("external-sample");
    if (!created || created.value()->id() != "inproc") return 2;
    registration.reset();
    if (registry.create("external-sample")) return 3;
    std::cout << "PDR_TRANSPORT_PROVIDER_EXTERNAL_PASS\n";
    return 0;
}
