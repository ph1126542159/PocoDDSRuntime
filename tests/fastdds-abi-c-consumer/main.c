#include <PocoDDS/DDS/AbiV1.h>

#include <stdint.h>
#include <stdio.h>

static int fail(const char* stage, int32_t status, const char* error)
{
    fprintf(stderr, "FAST_DDS_ABI_C_CONSUMER_FAIL stage=%s status=%d error=%s\n",
            stage, (int) status, error != NULL ? error : "");
    return 1;
}

int main(void)
{
    char error[512] = {0};
    PdrFastDdsRuntimeV1* runtime = NULL;
    int32_t started = -1;
    int32_t status;

    if (pdr_fastdds_abi_version_v1() != PDR_FASTDDS_ABI_VERSION_V1)
        return fail("version", PDR_FASTDDS_STATUS_V1_RUNTIME_ERROR, "unexpected ABI version");
    if (pdr_fastdds_envelope_size_v1() != sizeof(PdrFastDdsEnvelopeV1))
        return fail("layout", PDR_FASTDDS_STATUS_V1_RUNTIME_ERROR,
                    "envelope size differs across the DLL boundary");

    status = pdr_fastdds_runtime_create_v1(
        61u, "pdr-fastdds-abi-c-consumer", &runtime, error, sizeof(error));
    if (status != PDR_FASTDDS_STATUS_V1_OK || runtime == NULL)
        return fail("create", status, error);

    status = pdr_fastdds_runtime_started_v1(runtime, &started, error, sizeof(error));
    if (status != PDR_FASTDDS_STATUS_V1_OK || started != 0)
    {
        pdr_fastdds_runtime_destroy_v1(runtime);
        return fail("initial-state", status, error);
    }
    status = pdr_fastdds_runtime_start_v1(runtime, error, sizeof(error));
    if (status != PDR_FASTDDS_STATUS_V1_OK)
    {
        pdr_fastdds_runtime_destroy_v1(runtime);
        return fail("start", status, error);
    }
    status = pdr_fastdds_runtime_stop_v1(runtime, error, sizeof(error));
    if (status != PDR_FASTDDS_STATUS_V1_OK)
    {
        pdr_fastdds_runtime_destroy_v1(runtime);
        return fail("stop", status, error);
    }
    pdr_fastdds_runtime_destroy_v1(runtime);
    puts("FAST_DDS_ABI_C_CONSUMER_PASS language=C layout=verified lifecycle=verified");
    return 0;
}
