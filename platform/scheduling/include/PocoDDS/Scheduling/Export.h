#pragma once

#if defined(_WIN32) && !defined(PDR_SCHEDULING_STATIC)
#if defined(PDRSchedulingCore_EXPORTS)
#define PDR_SCHEDULING_API __declspec(dllexport)
#else
#define PDR_SCHEDULING_API __declspec(dllimport)
#endif
#else
#define PDR_SCHEDULING_API
#endif
