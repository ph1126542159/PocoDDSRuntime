#include "PocoDDS/OSP/DependencyResolver.h"
#include <gtest/gtest.h>

TEST(DependencyResolverTest, StartsDependenciesBeforeConsumers)
{
    PocoDDS::OSP::DependencyResolver resolver;
    PocoDDS::OSP::BundleManifest renderer{"demo.renderer", "1.0.0", "Renderer", {}};
    PocoDDS::OSP::BundleManifest shell{
        "demo.shell", "1.0.0", "Shell", {{"demo.renderer", "1.0.0", false}}};
    const auto resolved = resolver.resolve({shell, renderer});
    ASSERT_EQ(resolved.size(), 2U);
    EXPECT_EQ(resolved[0].symbolicName, "demo.renderer");
    EXPECT_EQ(resolved[1].symbolicName, "demo.shell");
}

TEST(DependencyResolverTest, RejectsCycles)
{
    PocoDDS::OSP::DependencyResolver resolver;
    PocoDDS::OSP::BundleManifest a{"a", "1", "A", {{"b", "1", false}}};
    PocoDDS::OSP::BundleManifest b{"b", "1", "B", {{"a", "1", false}}};
    EXPECT_THROW(resolver.resolve({a, b}), std::runtime_error);
}
