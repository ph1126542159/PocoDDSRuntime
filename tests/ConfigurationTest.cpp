#include "PocoDDS/Core/Configuration.h"
#include <gtest/gtest.h>

TEST(ConfigurationTest, AppliesValidatedChangesAtomically)
{
    PocoDDS::Core::Configuration configuration;
    configuration.addValidator(
        [](const auto& values) -> std::optional<std::string>
        {
            const auto port = values.find("admin.port");
            if (port != values.end() && port->second == "0")
                return "admin.port must not be zero";
            return std::nullopt;
        });
    configuration.apply({{"admin.port", "8080"}, {"admin.bind", "127.0.0.1"}});
    EXPECT_EQ(configuration.get("admin.port"), "8080");
    EXPECT_THROW(configuration.apply({{"admin.port", "0"}, {"admin.bind", "0.0.0.0"}}),
                 std::invalid_argument);
    EXPECT_EQ(configuration.get("admin.port"), "8080");
    EXPECT_EQ(configuration.get("admin.bind"), "127.0.0.1");
}

TEST(ConfigurationTest, RollsBackWhenLiveApplyFails)
{
    PocoDDS::Core::Configuration configuration;
    configuration.apply({{"mode", "safe"}});
    configuration.observe(
        [](const auto&, const auto& after)
        {
            if (after.at("mode") == "unsafe")
                throw std::runtime_error("apply failed");
        });
    EXPECT_THROW(configuration.apply({{"mode", "unsafe"}}), std::runtime_error);
    EXPECT_EQ(configuration.get("mode"), "safe");
}
