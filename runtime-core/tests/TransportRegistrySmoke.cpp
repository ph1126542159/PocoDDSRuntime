#include "PocoDDS/RuntimeCore/InProcessTransport.h"
#include "PocoDDS/RuntimeCore/TransportRegistry.h"

#include <iostream>
#include <memory>

int main()
{
    using namespace PocoDDS::RuntimeCore;

    TransportRegistry registry;
    auto builtin = registerInProcessTransport(registry);
    if (!builtin)
        return 1;
    auto builtinRegistration = std::move(builtin).value();
    if (!registry.create("inproc"))
        return 2;
    builtinRegistration.reset();

    auto registered = registry.registerFactory(
        {"inproc", "1.0.0", {true, false, false, false, false, true}, {"executor"}},
        [](const TransportConfiguration& configuration)
        {
            if (configuration.count("reject") != 0)
                return Outcome<std::shared_ptr<IMessageTransport>>::failure(
                    {RuntimeErrorCode::invalidArgument, "rejected test configuration", false});
            return Outcome<std::shared_ptr<IMessageTransport>>::success(
                std::make_shared<InProcessTransport>());
        });
    if (!registered)
        return 3;
    auto registration = std::move(registered).value();

    const auto duplicate =
        registry.registerFactory({"inproc", "1.0.0", {}, {}},
                                 [](const TransportConfiguration&)
                                 {
                                     return Outcome<std::shared_ptr<IMessageTransport>>::success(
                                         std::make_shared<InProcessTransport>());
                                 });
    if (duplicate || duplicate.error().code != RuntimeErrorCode::invalidArgument)
        return 4;
    const auto descriptors = registry.descriptors();
    if (descriptors.size() != 1 || descriptors.front().id != "inproc" ||
        !descriptors.front().capabilities.inProcess)
        return 5;
    const auto transport = registry.create("inproc");
    if (!transport || transport.value()->id() != "inproc")
        return 6;
    const auto rejected = registry.create("inproc", {{"reject", "true"}});
    if (rejected || rejected.error().code != RuntimeErrorCode::invalidArgument)
        return 7;
    const auto missing = registry.create("ros2");
    if (missing || missing.error().code != RuntimeErrorCode::unsupported)
        return 8;

    registration.reset();
    if (!registry.descriptors().empty())
        return 9;
    std::cout << "PDR_RUNTIME_CORE_TRANSPORT_REGISTRY_PASS duplicate=rejected lifetime=raii\n";
    return 0;
}
