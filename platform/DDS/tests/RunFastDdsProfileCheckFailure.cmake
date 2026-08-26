foreach(required PDR_FASTDDS_PROFILE_CHECK PDR_FASTDDS_INVALID_PROFILE
                 PDR_FASTDDS_EXPECTED_ERROR)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR
            "RunFastDdsProfileCheckFailure.cmake requires ${required}")
    endif()
endforeach()

set(check_command
    "${PDR_FASTDDS_PROFILE_CHECK}" --profile "${PDR_FASTDDS_INVALID_PROFILE}")
if(DEFINED PDR_FASTDDS_EXPECTED_SHA256)
    list(APPEND check_command --sha256 "${PDR_FASTDDS_EXPECTED_SHA256}")
endif()

execute_process(
    COMMAND ${check_command}
    RESULT_VARIABLE check_result
    OUTPUT_VARIABLE check_output
    ERROR_VARIABLE check_error)
if(NOT check_result EQUAL 1 OR
        NOT check_error MATCHES
            "PDR_FASTDDS_PROFILE_CHECK_ERROR: ${PDR_FASTDDS_EXPECTED_ERROR}")
    message(FATAL_ERROR
        "Fast DDS invalid profile was not rejected deterministically "
        "(exit=${check_result})\n${check_output}\n${check_error}")
endif()

message(STATUS "PDR_FASTDDS_PROFILE_CHECK_NEGATIVE_PASS exit=${check_result}")
