#include "Poco/OSP/Bundle.h"
#include "Poco/OSP/BundleContextFactory.h"
#include "Poco/OSP/BundleFactory.h"
#include "Poco/OSP/BundleLifecycleGuard.h"
#include "Poco/OSP/BundleLoader.h"
#include "Poco/OSP/CodeCache.h"
#include "Poco/OSP/LanguageTag.h"
#include "Poco/OSP/Properties.h"
#include "Poco/OSP/ServiceRegistry.h"
#include "Poco/OSP/SystemEvents.h"

#include <Poco/AutoPtr.h>

#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>

namespace
{
class CountingGuard final : public Poco::OSP::BundleLifecycleGuard
{
public:
    CountingGuard(bool allowStart, std::string code)
        : _allowStart(allowStart), _code(std::move(code))
    {
    }

    Poco::OSP::BundleLifecycleDecision evaluateStart(
        const std::string&) const override
    {
        ++startCalls;
        return {_allowStart, _allowStart ? std::string() : _code,
                _allowStart ? std::string() : "expected smoke rejection", {}};
    }

    Poco::OSP::BundleLifecycleDecision evaluateStop(
        const std::string&) const override
    {
        ++stopCalls;
        return {true, {}, {}, {}};
    }

    mutable int startCalls{0};
    mutable int stopCalls{0};

private:
    bool _allowStart;
    std::string _code;
};
} // namespace

int main(int argc, char** argv)
{
    if (argc != 3)
    {
        std::cerr << "usage: pdr-osp-composite-guard-smoke <bundle> <cache>\n";
        return 2;
    }

    try
    {
        Poco::OSP::CodeCache cache(argv[2]);
        Poco::OSP::ServiceRegistry registry;
        Poco::OSP::LanguageTag language("en", "US");
        Poco::OSP::BundleFactory::Ptr factory(
            new Poco::OSP::BundleFactory(language));
        Poco::OSP::SystemEvents events;
        Poco::OSP::BundleContextFactory::Ptr contexts(
            new Poco::OSP::BundleContextFactory(registry, events));
        Poco::OSP::BundleLoader loader(cache, factory, contexts);

        Poco::AutoPtr<CountingGuard> allow = new CountingGuard(true, "");
        Poco::AutoPtr<CountingGuard> reject =
            new CountingGuard(false, "SECOND_GUARD_REJECTED");
        Poco::OSP::Properties properties;
        properties.set("pdr.lifecycle.guard", "smoke");
        const auto allowRef = registry.registerService(
            "a.smoke.lifecycleGuard", allow, properties);
        const auto rejectRef = registry.registerService(
            "b.smoke.lifecycleGuard", reject, properties);

        Poco::OSP::Bundle::Ptr bundle = loader.loadBundle(argv[1]);
        bundle->resolve();
        bool rejected = false;
        try
        {
            bundle->start();
        }
        catch (const std::runtime_error& exception)
        {
            rejected = std::string(exception.what()).find(
                "SECOND_GUARD_REJECTED") != std::string::npos;
        }
        if (!rejected || allow->startCalls != 1 || reject->startCalls != 1 ||
            bundle->state() != Poco::OSP::Bundle::BUNDLE_RESOLVED)
            throw std::runtime_error(
                "all advertised lifecycle guards were not enforced");

        registry.unregisterService(rejectRef);
        bundle->start();
        if (allow->startCalls != 2 || !bundle->isActive())
            throw std::runtime_error(
                "bundle did not start after rejecting guard removal");
        bundle->stop();
        if (allow->stopCalls != 1)
            throw std::runtime_error("remaining guard did not observe stop");
        registry.unregisterService(allowRef);

        std::cout << "OSP_COMPOSITE_LIFECYCLE_GUARD_PASS "
                     "startGuards=2 stopGuards=1\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "OSP_COMPOSITE_LIFECYCLE_GUARD_FAIL "
                  << exception.what() << '\n';
        return 1;
    }
}
