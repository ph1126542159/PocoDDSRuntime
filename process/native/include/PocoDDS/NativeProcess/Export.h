#pragma once

#if defined(_WIN32) && !defined(PDR_NATIVE_PROCESS_STATIC)
#if defined(PDRNativeProcess_EXPORTS)
#define PDR_NATIVE_PROCESS_API __declspec(dllexport)
#else
#define PDR_NATIVE_PROCESS_API __declspec(dllimport)
#endif
#else
#define PDR_NATIVE_PROCESS_API
#endif
