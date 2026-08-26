#pragma once

#if defined(_WIN32) && !defined(PDR_SERVICE_CLIENT_TESTING_STATIC)
#if defined(PDRServiceClientTesting_EXPORTS)
#define PDR_SERVICE_CLIENT_TESTING_API __declspec(dllexport)
#else
#define PDR_SERVICE_CLIENT_TESTING_API __declspec(dllimport)
#endif
#else
#define PDR_SERVICE_CLIENT_TESTING_API
#endif
