#pragma once

#if defined(_WIN32) && !defined(PDR_SERVICE_DEPENDENCY_STATIC)
#if defined(PDRServiceDependencyCore_EXPORTS)
#define PDR_SERVICE_DEPENDENCY_API __declspec(dllexport)
#else
#define PDR_SERVICE_DEPENDENCY_API __declspec(dllimport)
#endif
#else
#define PDR_SERVICE_DEPENDENCY_API
#endif

