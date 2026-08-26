#pragma once

#if defined(PDR_LIFECYCLE_STATIC)
#define PDR_LIFECYCLE_API
#elif defined(PDRLifecycleCore_EXPORTS)
#define PDR_LIFECYCLE_API __declspec(dllexport)
#else
#define PDR_LIFECYCLE_API __declspec(dllimport)
#endif

#if !defined(_WIN32)
#undef PDR_LIFECYCLE_API
#if defined(PDR_LIFECYCLE_STATIC)
#define PDR_LIFECYCLE_API
#else
#define PDR_LIFECYCLE_API __attribute__((visibility("default")))
#endif
#endif
