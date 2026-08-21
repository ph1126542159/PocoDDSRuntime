#pragma once

#include "PocoDDS/Robotics/Business.h"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

namespace PocoDDS::Robotics
{
inline constexpr std::uint32_t businessPluginAbiVersion = 1;
inline constexpr const char* businessPluginEntryPoint = "pdrBusinessPluginV1";

struct BusinessPluginDescriptor
{
    std::size_t structureSize{sizeof(BusinessPluginDescriptor)};
    std::uint32_t abiVersion{businessPluginAbiVersion};
    const char* name{nullptr};
    RobotBusinessModule* (*create)(){nullptr};
    void (*destroy)(RobotBusinessModule*) noexcept {nullptr};
};

using BusinessPluginEntry = const BusinessPluginDescriptor* (*)();

class BusinessPluginLoader
{
  public:
    static std::shared_ptr<RobotBusinessModule> load(const std::string& path);
};
} // namespace PocoDDS::Robotics

#if defined(_WIN32)
#define PDR_BUSINESS_PLUGIN_EXPORT extern "C" __declspec(dllexport)
#else
#define PDR_BUSINESS_PLUGIN_EXPORT extern "C" __attribute__((visibility("default")))
#endif
