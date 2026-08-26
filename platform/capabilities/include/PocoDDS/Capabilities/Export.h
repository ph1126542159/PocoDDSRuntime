#pragma once

#if defined(_WIN32) && !defined(PDR_CAPABILITIES_STATIC)
#if defined(PDRCapabilitiesCore_EXPORTS)
#define PDR_CAPABILITIES_API __declspec(dllexport)
#else
#define PDR_CAPABILITIES_API __declspec(dllimport)
#endif
#else
#define PDR_CAPABILITIES_API
#endif
