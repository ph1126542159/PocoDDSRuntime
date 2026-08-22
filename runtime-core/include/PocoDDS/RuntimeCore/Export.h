#pragma once

#if defined(_WIN32) && !defined(PDR_RUNTIME_CORE_STATIC)
#if defined(PDRRuntimeCore_EXPORTS)
#define PDR_RUNTIME_CORE_API __declspec(dllexport)
#else
#define PDR_RUNTIME_CORE_API __declspec(dllimport)
#endif
#else
#define PDR_RUNTIME_CORE_API
#endif
