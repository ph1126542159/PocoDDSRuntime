#pragma once

#if defined(_WIN32) && !defined(PDR_CONFIG_TRANSACTION_STATIC)
#if defined(PDRConfigTransactionCore_EXPORTS)
#define PDR_CONFIG_TRANSACTION_API __declspec(dllexport)
#else
#define PDR_CONFIG_TRANSACTION_API __declspec(dllimport)
#endif
#else
#define PDR_CONFIG_TRANSACTION_API
#endif
