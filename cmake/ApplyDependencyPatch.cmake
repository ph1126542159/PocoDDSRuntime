if(NOT DEFINED PDR_PATCH_SOURCE_DIR OR NOT IS_DIRECTORY "${PDR_PATCH_SOURCE_DIR}")
    message(FATAL_ERROR "PDR_PATCH_SOURCE_DIR must name an existing dependency source directory")
endif()
if(NOT DEFINED PDR_PATCH_FILE OR NOT EXISTS "${PDR_PATCH_FILE}")
    message(FATAL_ERROR "PDR_PATCH_FILE must name an existing patch file")
endif()
if(NOT DEFINED PDR_GIT_EXECUTABLE OR NOT EXISTS "${PDR_GIT_EXECUTABLE}")
    message(FATAL_ERROR "PDR_GIT_EXECUTABLE must name the Git executable")
endif()

execute_process(
    COMMAND "${PDR_GIT_EXECUTABLE}" apply --reverse --check "${PDR_PATCH_FILE}"
    WORKING_DIRECTORY "${PDR_PATCH_SOURCE_DIR}"
    RESULT_VARIABLE _reverse_result
    OUTPUT_QUIET
    ERROR_QUIET)
if(_reverse_result EQUAL 0)
    message(STATUS "Dependency patch already applied: ${PDR_PATCH_FILE}")
    return()
endif()

execute_process(
    COMMAND "${PDR_GIT_EXECUTABLE}" apply --check "${PDR_PATCH_FILE}"
    WORKING_DIRECTORY "${PDR_PATCH_SOURCE_DIR}"
    RESULT_VARIABLE _check_result
    OUTPUT_VARIABLE _check_output
    ERROR_VARIABLE _check_error)
if(NOT _check_result EQUAL 0)
    message(FATAL_ERROR
        "Dependency patch does not apply cleanly: ${PDR_PATCH_FILE}\n"
        "${_check_output}${_check_error}")
endif()

execute_process(
    COMMAND "${PDR_GIT_EXECUTABLE}" apply "${PDR_PATCH_FILE}"
    WORKING_DIRECTORY "${PDR_PATCH_SOURCE_DIR}"
    RESULT_VARIABLE _apply_result
    OUTPUT_VARIABLE _apply_output
    ERROR_VARIABLE _apply_error)
if(NOT _apply_result EQUAL 0)
    message(FATAL_ERROR
        "Dependency patch failed: ${PDR_PATCH_FILE}\n"
        "${_apply_output}${_apply_error}")
endif()
message(STATUS "Applied dependency patch: ${PDR_PATCH_FILE}")
