#pragma once

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#define PDR_FASTDDS_ABI_V1_CALL __cdecl
#if defined(PDRFastDDSAbiV1_EXPORTS)
#define PDR_FASTDDS_ABI_V1_API __declspec(dllexport)
#else
#define PDR_FASTDDS_ABI_V1_API __declspec(dllimport)
#endif
#elif defined(__GNUC__) || defined(__clang__)
#define PDR_FASTDDS_ABI_V1_CALL
#define PDR_FASTDDS_ABI_V1_API __attribute__((visibility("default")))
#else
#define PDR_FASTDDS_ABI_V1_CALL
#define PDR_FASTDDS_ABI_V1_API
#endif

#ifdef __cplusplus
extern "C"
{
#endif

#define PDR_FASTDDS_ABI_VERSION_V1 1u

typedef struct PdrFastDdsRuntimeV1 PdrFastDdsRuntimeV1;
typedef struct PdrFastDdsSubscriptionV1 PdrFastDdsSubscriptionV1;

typedef enum PdrFastDdsStatusV1
{
    PDR_FASTDDS_STATUS_V1_OK = 0,
    PDR_FASTDDS_STATUS_V1_INVALID_ARGUMENT = 1,
    PDR_FASTDDS_STATUS_V1_INVALID_STATE = 2,
    PDR_FASTDDS_STATUS_V1_RUNTIME_ERROR = 3,
    PDR_FASTDDS_STATUS_V1_UNKNOWN_ERROR = 4
} PdrFastDdsStatusV1;

typedef struct PdrFastDdsEnvelopeV1
{
    uint32_t struct_size;
    uint64_t sequence;
    int64_t timestamp_microseconds;
    const char* kind;
    const char* device_id;
    const char* operation;
    const char* payload;
    const char* correlation_id;
    const char* trace_parent;
    const char* trace_state;
    const char* business_name;
    const char* business_instance_id;
    int32_t status;
} PdrFastDdsEnvelopeV1;

/* String pointers received by the callback remain valid only for the callback duration. */
typedef void (PDR_FASTDDS_ABI_V1_CALL *PdrFastDdsEnvelopeHandlerV1)(
    const PdrFastDdsEnvelopeV1* envelope,
    void* user_data);

PDR_FASTDDS_ABI_V1_API uint32_t PDR_FASTDDS_ABI_V1_CALL
pdr_fastdds_abi_version_v1(void);

PDR_FASTDDS_ABI_V1_API uint32_t PDR_FASTDDS_ABI_V1_CALL
pdr_fastdds_envelope_size_v1(void);

PDR_FASTDDS_ABI_V1_API int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_create_v1(
    uint32_t domain_id,
    const char* participant_name,
    PdrFastDdsRuntimeV1** runtime,
    char* error_message,
    size_t error_capacity);

PDR_FASTDDS_ABI_V1_API void PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_destroy_v1(
    PdrFastDdsRuntimeV1* runtime);

PDR_FASTDDS_ABI_V1_API int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_start_v1(
    PdrFastDdsRuntimeV1* runtime,
    char* error_message,
    size_t error_capacity);

PDR_FASTDDS_ABI_V1_API int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_stop_v1(
    PdrFastDdsRuntimeV1* runtime,
    char* error_message,
    size_t error_capacity);

PDR_FASTDDS_ABI_V1_API int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_started_v1(
    const PdrFastDdsRuntimeV1* runtime,
    int32_t* started,
    char* error_message,
    size_t error_capacity);

PDR_FASTDDS_ABI_V1_API int32_t PDR_FASTDDS_ABI_V1_CALL
pdr_fastdds_runtime_prepare_publisher_v1(
    PdrFastDdsRuntimeV1* runtime,
    const char* topic,
    char* error_message,
    size_t error_capacity);

PDR_FASTDDS_ABI_V1_API int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_publish_v1(
    PdrFastDdsRuntimeV1* runtime,
    const char* topic,
    const PdrFastDdsEnvelopeV1* envelope,
    char* error_message,
    size_t error_capacity);

PDR_FASTDDS_ABI_V1_API int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_subscribe_v1(
    PdrFastDdsRuntimeV1* runtime,
    const char* topic,
    PdrFastDdsEnvelopeHandlerV1 handler,
    void* user_data,
    PdrFastDdsSubscriptionV1** subscription,
    char* error_message,
    size_t error_capacity);

PDR_FASTDDS_ABI_V1_API int32_t PDR_FASTDDS_ABI_V1_CALL
pdr_fastdds_subscription_unsubscribe_v1(
    PdrFastDdsSubscriptionV1* subscription,
    char* error_message,
    size_t error_capacity);

PDR_FASTDDS_ABI_V1_API void PDR_FASTDDS_ABI_V1_CALL
pdr_fastdds_subscription_destroy_v1(
    PdrFastDdsSubscriptionV1* subscription);

#ifdef __cplusplus
}
#endif
