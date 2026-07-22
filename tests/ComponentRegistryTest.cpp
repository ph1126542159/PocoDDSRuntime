#include "PocoDDS/Core/ComponentRegistry.h"
#include <gtest/gtest.h>

TEST(ComponentRegistryTest, UpsertAndDiscoverComponent)
{
    PocoDDS::Core::ComponentRegistry registry;
    registry.upsert({"service-1",
                     "renderer",
                     "node-a",
                     42,
                     PocoDDS::Core::ComponentKind::Service,
                     PocoDDS::Core::ComponentState::Running,
                     {}});
    const auto component = registry.find("service-1");
    ASSERT_TRUE(component.has_value());
    EXPECT_EQ(component->name, "renderer");
}
