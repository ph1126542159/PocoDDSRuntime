#pragma once

#if defined(_WIN32) && !defined(PDR_MEMBERSHIP_STATIC)
#if defined(PDRMembershipCore_EXPORTS)
#define PDR_MEMBERSHIP_API __declspec(dllexport)
#else
#define PDR_MEMBERSHIP_API __declspec(dllimport)
#endif
#else
#define PDR_MEMBERSHIP_API
#endif

#if defined(_WIN32) && !defined(PDR_MEMBERSHIP_PERSISTENCE_STATIC)
#if defined(PDRMembershipPersistence_EXPORTS)
#define PDR_MEMBERSHIP_PERSISTENCE_API __declspec(dllexport)
#else
#define PDR_MEMBERSHIP_PERSISTENCE_API __declspec(dllimport)
#endif
#else
#define PDR_MEMBERSHIP_PERSISTENCE_API
#endif
