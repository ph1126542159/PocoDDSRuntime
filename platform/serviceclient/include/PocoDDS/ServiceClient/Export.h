#pragma once

#if defined(_WIN32) && !defined(PDR_SERVICE_CLIENT_STATIC)
#if defined(PDRServiceClientCore_EXPORTS)
#define PDR_SERVICE_CLIENT_API __declspec(dllexport)
#else
#define PDR_SERVICE_CLIENT_API __declspec(dllimport)
#endif
#else
#define PDR_SERVICE_CLIENT_API
#endif

#if defined(_WIN32) && !defined(PDR_SERVICE_CLIENT_OSP_STATIC)
#if defined(PDRServiceClientAPI_EXPORTS)
#define PDR_SERVICE_CLIENT_OSP_API __declspec(dllexport)
#else
#define PDR_SERVICE_CLIENT_OSP_API __declspec(dllimport)
#endif
#else
#define PDR_SERVICE_CLIENT_OSP_API
#endif
