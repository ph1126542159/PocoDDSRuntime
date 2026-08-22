#pragma once

#if defined(_WIN32) && !defined(PDR_FASTDDS_TRANSPORT_STATIC)
#if defined(PDRFastDdsTransport_EXPORTS)
#define PDR_FASTDDS_TRANSPORT_API __declspec(dllexport)
#else
#define PDR_FASTDDS_TRANSPORT_API __declspec(dllimport)
#endif
#else
#define PDR_FASTDDS_TRANSPORT_API
#endif
