#pragma once

#if defined(_WIN32) && !defined(PDR_RESOURCE_GOVERNANCE_STATIC)
#if defined(PDRResourceGovernanceCore_EXPORTS)
#define PDR_RESOURCE_GOVERNANCE_API __declspec(dllexport)
#else
#define PDR_RESOURCE_GOVERNANCE_API __declspec(dllimport)
#endif
#else
#define PDR_RESOURCE_GOVERNANCE_API
#endif

#if defined(_WIN32) && !defined(PDR_RESOURCE_GOVERNANCE_OSP_STATIC)
#if defined(PDRResourceGovernanceAPI_EXPORTS)
#define PDR_RESOURCE_GOVERNANCE_OSP_API __declspec(dllexport)
#else
#define PDR_RESOURCE_GOVERNANCE_OSP_API __declspec(dllimport)
#endif
#else
#define PDR_RESOURCE_GOVERNANCE_OSP_API
#endif
