#pragma once

#if defined(_WIN32) && !defined(PDR_SCHEDULING_CONFIGURATION_STATIC)
#if defined(PDRSchedulingConfiguration_EXPORTS)
#define PDR_SCHEDULING_CONFIGURATION_API __declspec(dllexport)
#else
#define PDR_SCHEDULING_CONFIGURATION_API __declspec(dllimport)
#endif
#else
#define PDR_SCHEDULING_CONFIGURATION_API
#endif
