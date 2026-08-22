#pragma once

#if defined(_WIN32) && !defined(PDR_RUNTIME_CORE_TESTING_STATIC)
#if defined(PDRRuntimeCoreTesting_EXPORTS)
#define PDR_RUNTIME_CORE_TESTING_API __declspec(dllexport)
#else
#define PDR_RUNTIME_CORE_TESTING_API __declspec(dllimport)
#endif
#else
#define PDR_RUNTIME_CORE_TESTING_API
#endif
