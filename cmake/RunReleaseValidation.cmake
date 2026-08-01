set(release_dir "${PDR_BINARY_DIR}/reports/release-smoke")
execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/release_manifest.py" generate
        --root "${PDR_SOURCE_DIR}"
        --artifacts "${PDR_BINARY_DIR}/bin"
        --output "${release_dir}"
        --version "${PDR_VERSION}"
    RESULT_VARIABLE generate_result)
if(NOT generate_result EQUAL 0)
    message(FATAL_ERROR "Release manifest generation failed: ${generate_result}")
endif()
execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/release_manifest.py" verify
        --manifest "${release_dir}/SHA256SUMS.json"
        --artifacts "${PDR_BINARY_DIR}/bin"
    RESULT_VARIABLE verify_result)
if(NOT verify_result EQUAL 0)
    message(FATAL_ERROR "Release manifest verification failed: ${verify_result}")
endif()
