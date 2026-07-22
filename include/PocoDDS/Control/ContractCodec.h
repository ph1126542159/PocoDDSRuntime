#pragma once

#include "PocoDDS/Control/Contracts.h"

#include <cstddef>
#include <vector>

namespace PocoDDS::Control
{
std::vector<std::byte> encode(const ComponentManifest& value);
std::vector<std::byte> encode(const ConfigurationTransaction& value);
std::vector<std::byte> encode(const LifecycleCommand& value);
std::vector<std::byte> encode(const CommandResult& value);

ComponentManifest decodeComponentManifest(const std::vector<std::byte>& data);
ConfigurationTransaction decodeConfigurationTransaction(const std::vector<std::byte>& data);
LifecycleCommand decodeLifecycleCommand(const std::vector<std::byte>& data);
CommandResult decodeCommandResult(const std::vector<std::byte>& data);
} // namespace PocoDDS::Control
