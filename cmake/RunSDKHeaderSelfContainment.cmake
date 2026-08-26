foreach(required PDR_CMAKE PDR_PYTHON PDR_SOURCE_DIR PDR_BINARY_DIR
                 PDR_CONFIG PDR_GENERATOR PDR_DEPENDENCY_PREFIX)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR
            "RunSDKHeaderSelfContainment.cmake requires ${required}")
    endif()
endforeach()

set(prefix "${PDR_BINARY_DIR}/sdk-header-self-containment-install")
set(project_dir "${PDR_BINARY_DIR}/sdk-header-self-containment-project")
set(build_dir "${PDR_BINARY_DIR}/sdk-header-self-containment-build")
set(plan "${PDR_BINARY_DIR}/reports/sdk-header-self-containment-plan.json")
set(evidence "${PDR_BINARY_DIR}/reports/sdk-header-self-containment-evidence.json")
file(REMOVE_RECURSE "${prefix}" "${project_dir}" "${build_dir}")
file(MAKE_DIRECTORY "${PDR_BINARY_DIR}/reports")

execute_process(
    COMMAND "${PDR_CMAKE}" --install "${PDR_BINARY_DIR}"
            --config "${PDR_CONFIG}" --prefix "${prefix}"
    RESULT_VARIABLE install_result
    OUTPUT_VARIABLE install_output
    ERROR_VARIABLE install_error)
if(NOT install_result EQUAL 0)
    message(FATAL_ERROR
        "SDK header test install failed (${install_result})\n"
        "${install_output}\n${install_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/sdk_header_self_containment.py"
            generate --install "${prefix}" --output "${project_dir}" --plan "${plan}"
    RESULT_VARIABLE generate_result
    OUTPUT_VARIABLE generate_output
    ERROR_VARIABLE generate_error)
if(NOT generate_result EQUAL 0)
    message(FATAL_ERROR
        "SDK header test generation failed (${generate_result})\n"
        "${generate_output}\n${generate_error}")
endif()

set(prefix_path "${prefix}\\;${PDR_DEPENDENCY_PREFIX}")
set(configure_command
    "${PDR_CMAKE}" -S "${project_dir}" -B "${build_dir}"
    -G "${PDR_GENERATOR}"
    "-DCMAKE_PREFIX_PATH=${prefix_path}"
    "-DPoco_DIR=${PDR_DEPENDENCY_PREFIX}/cmake")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND configure_command -A "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(
    COMMAND ${configure_command}
    RESULT_VARIABLE configure_result
    OUTPUT_VARIABLE configure_output
    ERROR_VARIABLE configure_error)
if(NOT configure_result EQUAL 0)
    message(FATAL_ERROR
        "SDK header test configure failed (${configure_result})\n"
        "${configure_output}\n${configure_error}")
endif()

execute_process(
    COMMAND "${PDR_CMAKE}" --build "${build_dir}" --config "${PDR_CONFIG}"
            --target pdr-sdk-header-self-containment --parallel 2
    RESULT_VARIABLE build_result
    OUTPUT_VARIABLE build_output
    ERROR_VARIABLE build_error)
if(NOT build_result EQUAL 0)
    message(FATAL_ERROR
        "SDK public header is not self-contained (${build_result})\n"
        "${build_output}\n${build_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/sdk_header_self_containment.py"
            complete --plan "${plan}" --config "${PDR_CONFIG}" --evidence "${evidence}"
    RESULT_VARIABLE complete_result
    OUTPUT_VARIABLE complete_output
    ERROR_VARIABLE complete_error)
if(NOT complete_result EQUAL 0)
    message(FATAL_ERROR
        "SDK header evidence failed (${complete_result})\n"
        "${complete_output}\n${complete_error}")
endif()

message(STATUS "${generate_output}${complete_output}")
