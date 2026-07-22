#pragma once

#include "PocoDDS/Core/Bundle.h"

#include <cstdint>

#if defined(_WIN32)
#define PDR_BUNDLE_EXPORT __declspec(dllexport)
#else
#define PDR_BUNDLE_EXPORT __attribute__((visibility("default")))
#endif

namespace PocoDDS::Core
{
inline constexpr std::uint32_t BundleAbiVersion = 1;

using BundleAbiVersionFunction = std::uint32_t (*)();
using CreateBundleFunction = Bundle* (*)();
using DestroyBundleFunction = void (*)(Bundle*);
} // namespace PocoDDS::Core
