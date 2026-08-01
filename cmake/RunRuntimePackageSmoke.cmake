foreach(required PDR_CMAKE PDR_PYTHON PDR_SOURCE_DIR PDR_BINARY_DIR
                 PDR_CONFIG PDR_RUNTIME_FILE_NAME PDR_CONFIG_CHECK_FILE_NAME)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR "RunRuntimePackageSmoke.cmake requires ${required}")
    endif()
endforeach()

set(prefix "${PDR_BINARY_DIR}/runtime-smoke-install")
set(report "${PDR_BINARY_DIR}/reports/runtime-package-smoke.json")
file(REMOVE_RECURSE "${prefix}")

execute_process(
    COMMAND "${PDR_CMAKE}" --install "${PDR_BINARY_DIR}"
            --config "${PDR_CONFIG}" --prefix "${prefix}"
    RESULT_VARIABLE install_result
    OUTPUT_VARIABLE install_output
    ERROR_VARIABLE install_error)
if(NOT install_result EQUAL 0)
    message(FATAL_ERROR
        "Runtime package install failed (${install_result})\n${install_output}\n${install_error}")
endif()

foreach(installed_tool pdr.py pdr.ps1 "${PDR_CONFIG_CHECK_FILE_NAME}")
    if(NOT EXISTS "${prefix}/bin/${installed_tool}")
        message(FATAL_ERROR "Installed Runtime package is missing CLI tool: ${installed_tool}")
    endif()
endforeach()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" validate-config
            "${prefix}/bin/pdr-runtime.properties"
            --report "${PDR_BINARY_DIR}/reports/runtime-package-config-validation.json"
    RESULT_VARIABLE config_check_result
    OUTPUT_VARIABLE config_check_output
    ERROR_VARIABLE config_check_error)
if(NOT config_check_result EQUAL 0)
    message(FATAL_ERROR
        "Installed runtime configuration validation failed (${config_check_result})\n"
        "${config_check_output}\n${config_check_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/runtime_smoke.py"
            --executable "${prefix}/bin/${PDR_RUNTIME_FILE_NAME}"
            --working-directory "${prefix}/bin"
            --timeout 20
            --stability-window 2
            --path "${prefix}/bin"
            --endpoint "/health/detail"
            --report "${report}"
    RESULT_VARIABLE smoke_result
    OUTPUT_VARIABLE smoke_output
    ERROR_VARIABLE smoke_error)
if(NOT smoke_result EQUAL 0)
    file(READ "${report}" report_content)
    message(FATAL_ERROR
        "Installed runtime smoke failed (${smoke_result})\n${smoke_output}\n${smoke_error}\n${report_content}")
endif()

message(STATUS "${config_check_output}${smoke_output}")
