#pragma once

#if defined(_WIN32) && !defined(PDR_TRANSPORT_PROVIDER_STATIC)
#if defined(PDRTransportProviderCore_EXPORTS)
#define PDR_TRANSPORT_PROVIDER_API __declspec(dllexport)
#else
#define PDR_TRANSPORT_PROVIDER_API __declspec(dllimport)
#endif
#else
#define PDR_TRANSPORT_PROVIDER_API
#endif
