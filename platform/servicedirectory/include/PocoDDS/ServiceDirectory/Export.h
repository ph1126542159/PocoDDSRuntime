#pragma once

#if defined(_WIN32) && !defined(PDR_SERVICE_DIRECTORY_STATIC)
#if defined(PDRServiceDirectoryCore_EXPORTS)
#define PDR_SERVICE_DIRECTORY_API __declspec(dllexport)
#else
#define PDR_SERVICE_DIRECTORY_API __declspec(dllimport)
#endif
#else
#define PDR_SERVICE_DIRECTORY_API
#endif
