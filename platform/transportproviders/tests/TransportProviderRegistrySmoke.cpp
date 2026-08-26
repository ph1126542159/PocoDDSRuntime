#include "PocoDDS/RuntimeCore/InProcessTransport.h"
#include "PocoDDS/TransportProviders/ProviderRegistration.h"

#include <Poco/AutoPtr.h>

#include <atomic>
#include <future>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
class TestProvider final : public PocoDDS::TransportProviders::TransportFactoryService
{
public:
    explicit TestProvider(std::string id, bool throwDescriptor = false)
        : _id(std::move(id)), _throwDescriptor(throwDescriptor)
    {
    }

    PocoDDS::RuntimeCore::TransportDescriptor descriptor() const override
    {
        if (_throwDescriptor) throw std::runtime_error("descriptor failure");
        return {_id, "1.0.0", {true, false, false, false, false, true}, {"fail"}};
    }

    PocoDDS::RuntimeCore::Outcome<
        std::shared_ptr<PocoDDS::RuntimeCore::IMessageTransport>>
    create(const PocoDDS::RuntimeCore::TransportConfiguration& configuration) const override
    {
        ++creates;
        if (configuration.count("throw") != 0)
            throw std::runtime_error("factory failure");
        if (configuration.count("fail") != 0)
            return PocoDDS::RuntimeCore::Outcome<
                std::shared_ptr<PocoDDS::RuntimeCore::IMessageTransport>>::failure(
                {PocoDDS::RuntimeCore::RuntimeErrorCode::unavailable,
                 "provider unavailable", true});
        return PocoDDS::RuntimeCore::Outcome<
            std::shared_ptr<PocoDDS::RuntimeCore::IMessageTransport>>::success(
            std::make_shared<PocoDDS::RuntimeCore::InProcessTransport>());
    }

    mutable std::atomic<unsigned int> creates{0};

private:
    std::string _id;
    bool _throwDescriptor{false};
};
} // namespace

int main()
{
    using namespace PocoDDS::RuntimeCore;
    using namespace PocoDDS::TransportProviders;

    TransportRegistry registry;
    Poco::AutoPtr<TestProvider> owned = new TestProvider("dynamic");
    Poco::AutoPtr<TransportFactoryService> provider = owned;
    auto attached = registerTransportProvider(registry, provider);
    if (!attached) return 1;
    auto registration = std::move(attached).value();

    const auto descriptors = registry.descriptors();
    if (descriptors.size() != 1 || descriptors.front().id != "dynamic") return 2;

    std::vector<std::future<bool>> creates;
    for (unsigned int index = 0; index < 16; ++index)
        creates.push_back(std::async(std::launch::async, [&registry]
        {
            const auto result = registry.create("dynamic");
            return result && result.value()->id() == "inproc";
        }));
    for (auto& created : creates)
        if (!created.get()) return 3;
    if (owned->creates.load() != 16) return 4;

    const auto duplicate = registerTransportProvider(
        registry, Poco::AutoPtr<TransportFactoryService>(new TestProvider("dynamic")));
    if (duplicate || duplicate.error().code != RuntimeErrorCode::invalidArgument) return 5;

    const auto failed = registry.create("dynamic", {{"fail", "true"}});
    if (failed || failed.error().code != RuntimeErrorCode::unavailable ||
        !failed.error().retryable)
        return 6;
    const auto threw = registry.create("dynamic", {{"throw", "true"}});
    if (threw || threw.error().code != RuntimeErrorCode::internalError) return 7;

    const auto broken = registerTransportProvider(
        registry, Poco::AutoPtr<TransportFactoryService>(new TestProvider("broken", true)));
    if (broken || broken.error().code != RuntimeErrorCode::invalidArgument) return 8;

    registration.reset();
    if (registry.create("dynamic").error().code != RuntimeErrorCode::unsupported) return 9;

    std::cout << "PDR_TRANSPORT_PROVIDER_REGISTRY_PASS dynamic=true concurrency=16 "
                 "duplicate=rejected unload=raii exceptions=isolated\n";
    return 0;
}
