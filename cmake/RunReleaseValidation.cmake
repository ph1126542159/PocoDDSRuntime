foreach(required PDR_CMAKE PDR_PYTHON PDR_SOURCE_DIR PDR_BINARY_DIR PDR_CONFIG
                 PDR_VERSION PDR_REQUIRE_CLEAN)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR "RunReleaseValidation.cmake requires ${required}")
    endif()
endforeach()

set(release_dir "${PDR_BINARY_DIR}/reports/release-smoke")
set(install_dir "${PDR_BINARY_DIR}/release-smoke-install")
file(REMOVE_RECURSE "${release_dir}" "${install_dir}")
execute_process(
    COMMAND "${PDR_CMAKE}" --install "${PDR_BINARY_DIR}"
            --config "${PDR_CONFIG}" --prefix "${install_dir}"
    RESULT_VARIABLE install_result
    OUTPUT_VARIABLE install_output
    ERROR_VARIABLE install_error)
if(NOT install_result EQUAL 0)
    message(FATAL_ERROR
        "Release install failed (${install_result})\n${install_output}\n${install_error}")
endif()
set(generate_command
    "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/release_manifest.py" generate
        --root "${PDR_SOURCE_DIR}"
        --artifacts "${install_dir}"
        --output "${release_dir}"
        --version "${PDR_VERSION}")
if(PDR_REQUIRE_CLEAN)
    list(APPEND generate_command --require-clean)
endif()
execute_process(
    COMMAND ${generate_command}
    RESULT_VARIABLE generate_result)
if(NOT generate_result EQUAL 0)
    message(FATAL_ERROR "Release manifest generation failed: ${generate_result}")
endif()
execute_process(
    COMMAND "${PDR_PYTHON}" "${install_dir}/bin/release_manifest.py" verify
        --manifest "${release_dir}/SHA256SUMS.json"
        --artifacts "${install_dir}"
    RESULT_VARIABLE verify_result)
if(NOT verify_result EQUAL 0)
    message(FATAL_ERROR "Release manifest verification failed: ${verify_result}")
endif()
