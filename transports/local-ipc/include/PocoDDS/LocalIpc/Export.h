#pragma once

#if defined(_WIN32) && !defined(PDR_LOCAL_IPC_STATIC)
#if defined(PDRLocalIpc_EXPORTS)
#define PDR_LOCAL_IPC_API __declspec(dllexport)
#else
#define PDR_LOCAL_IPC_API __declspec(dllimport)
#endif
#else
#define PDR_LOCAL_IPC_API
#endif
