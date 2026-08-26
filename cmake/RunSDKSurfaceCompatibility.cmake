foreach(required PDR_CMAKE PDR_PYTHON PDR_SOURCE_DIR PDR_BINARY_DIR
                 PDR_CONFIG PDR_RUNTIME_VERSION)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR
            "RunSDKSurfaceCompatibility.cmake requires ${required}")
    endif()
endforeach()

set(prefix "${PDR_BINARY_DIR}/sdk-surface-install")
set(snapshot "${PDR_BINARY_DIR}/reports/sdk-public-surface.json")
set(report "${PDR_BINARY_DIR}/reports/sdk-public-surface-compatibility.json")
set(deprecation_report
    "${PDR_BINARY_DIR}/reports/sdk-deprecation-policy.json")
set(baseline
    "${PDR_SOURCE_DIR}/contracts/compatibility/sdk-surface-0.1.0.json")
set(deprecation_catalog
    "${PDR_SOURCE_DIR}/contracts/sdk-deprecations.json")
file(GLOB published_snapshots LIST_DIRECTORIES FALSE
    "${PDR_SOURCE_DIR}/contracts/compatibility/sdk-surface-*.json")
list(SORT published_snapshots)
list(FIND published_snapshots "${baseline}" baseline_snapshot_index)
if(baseline_snapshot_index EQUAL -1)
    message(FATAL_ERROR
        "SDK compatibility baseline is absent from published snapshots: ${baseline}")
endif()
file(REMOVE_RECURSE "${prefix}")
file(MAKE_DIRECTORY "${PDR_BINARY_DIR}/reports")

execute_process(
    COMMAND "${PDR_CMAKE}" --install "${PDR_BINARY_DIR}"
            --config "${PDR_CONFIG}" --prefix "${prefix}"
    RESULT_VARIABLE install_result
    OUTPUT_VARIABLE install_output
    ERROR_VARIABLE install_error)
if(NOT install_result EQUAL 0)
    message(FATAL_ERROR
        "SDK surface install failed (${install_result})\n"
        "${install_output}\n${install_error}")
endif()

set(snapshot_command
    "${PDR_PYTHON}" "${prefix}/bin/sdk_surface_guard.py" snapshot
    --install "${prefix}"
    --runtime-version "${PDR_RUNTIME_VERSION}"
    --output "${snapshot}")
if(DEFINED PDR_ABI_KEY OR DEFINED PDR_SYMBOL_TOOL)
    if(NOT DEFINED PDR_ABI_KEY OR NOT DEFINED PDR_SYMBOL_TOOL)
        message(FATAL_ERROR "PDR_ABI_KEY and PDR_SYMBOL_TOOL must be supplied together")
    endif()
    list(APPEND snapshot_command
        --abi-key "${PDR_ABI_KEY}" --symbol-tool "${PDR_SYMBOL_TOOL}")
endif()
execute_process(
    COMMAND ${snapshot_command}
    RESULT_VARIABLE snapshot_result
    OUTPUT_VARIABLE snapshot_output
    ERROR_VARIABLE snapshot_error)
if(NOT snapshot_result EQUAL 0)
    message(FATAL_ERROR
        "SDK surface snapshot failed (${snapshot_result})\n"
        "${snapshot_output}\n${snapshot_error}")
endif()

set(compare_command
    "${PDR_PYTHON}" "${prefix}/bin/sdk_surface_guard.py" compare
    --baseline "${baseline}"
    --current "${snapshot}"
    --report "${report}")
if(PDR_REQUIRE_ABI)
    list(APPEND compare_command --require-abi)
endif()
execute_process(
    COMMAND ${compare_command}
    RESULT_VARIABLE compare_result
    OUTPUT_VARIABLE compare_output
    ERROR_VARIABLE compare_error)

set(deprecation_command
    "${PDR_PYTHON}" "${prefix}/bin/sdk_deprecation_guard.py" validate
    --catalog "${deprecation_catalog}"
    --baseline "${baseline}"
    --current "${snapshot}"
    --install "${prefix}"
    --report "${deprecation_report}")
foreach(published_snapshot IN LISTS published_snapshots)
    list(APPEND deprecation_command
        --published-snapshot "${published_snapshot}")
endforeach()
execute_process(
    COMMAND ${deprecation_command}
    RESULT_VARIABLE deprecation_result
    OUTPUT_VARIABLE deprecation_output
    ERROR_VARIABLE deprecation_error)

if(NOT compare_result EQUAL 0 OR NOT deprecation_result EQUAL 0)
    message(FATAL_ERROR
        "SDK public surface governance failed "
        "(compatibility=${compare_result}, deprecation=${deprecation_result})\n"
        "${compare_output}\n${compare_error}\n"
        "${deprecation_output}\n${deprecation_error}")
endif()

message(STATUS
    "${snapshot_output}${compare_output}${deprecation_output}")
