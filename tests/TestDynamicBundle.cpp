#include "PocoDDS/Core/BundleContext.h"
#include "PocoDDS/Core/BundleLibrary.h"

namespace
{
class TestDynamicBundle final : public PocoDDS::Core::Bundle
{
  public:
    std::string name() const override { return "test.dynamic.bundle"; }

    void start(PocoDDS::Core::BundleContext&) override {}

    void stop(PocoDDS::Core::BundleContext&) override {}
};
} // namespace

extern "C" PDR_BUNDLE_EXPORT std::uint32_t pdrBundleAbiVersion()
{
    return PocoDDS::Core::BundleAbiVersion;
}

extern "C" PDR_BUNDLE_EXPORT PocoDDS::Core::Bundle* pdrCreateBundle()
{
    return new TestDynamicBundle;
}

extern "C" PDR_BUNDLE_EXPORT void pdrDestroyBundle(PocoDDS::Core::Bundle* bundle) { delete bundle; }
