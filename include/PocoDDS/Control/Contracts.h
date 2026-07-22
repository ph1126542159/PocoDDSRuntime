#pragma once

#include "PocoDDS/Core/Component.h"

#include <cstdint>
#include <map>
#include <string>

namespace PocoDDS::Control
{
inline constexpr std::uint16_t ContractVersion = 1;
inline constexpr const char* ComponentTopic = "pdr.control.component.v1";
inline constexpr const char* ConfigurationTopic = "pdr.control.configuration.v1";
inline constexpr const char* LifecycleTopic = "pdr.control.lifecycle.v1";
inline constexpr const char* ResultTopic = "pdr.control.result.v1";

struct ComponentManifest
{
    std::uint16_t version{ContractVersion};
    std::string nodeId;
    Core::Component component;
    std::int64_t heartbeatUnixMilliseconds{0};
    std::uint32_t leaseMilliseconds{5000};
};

struct ConfigurationTransaction
{
    std::uint16_t version{ContractVersion};
    std::string correlationId;
    std::string targetComponentId;
    std::uint64_t expectedRevision{0};
    std::map<std::string, std::string> changes;
};

enum class LifecycleAction : std::uint8_t
{
    Start,
    Stop,
    Restart,
    Uninstall
};

struct LifecycleCommand
{
    std::uint16_t version{ContractVersion};
    std::string correlationId;
    std::string targetComponentId;
    LifecycleAction action{LifecycleAction::Restart};
    std::uint32_t gracefulTimeoutMilliseconds{3000};
};

struct CommandResult
{
    std::uint16_t version{ContractVersion};
    std::string correlationId;
    std::string targetComponentId;
    bool success{false};
    std::string error;
    std::uint64_t configurationRevision{0};
};
} // namespace PocoDDS::Control
