foreach(required PDR_CONFIG_CHECK PDR_PYTHON PDR_TOOL PDR_VALID_CONFIG PDR_TEST_DIR)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR "RunConfigCheckTest.cmake requires ${required}")
    endif()
endforeach()

file(MAKE_DIRECTORY "${PDR_TEST_DIR}")
set(override "${PDR_TEST_DIR}/invalid.properties")
file(WRITE "${override}"
    "osp.web.server.port = 70000\n"
    "pdr.fastdds.domainId = 233\n")

execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_TOOL}" validate-config
            "${PDR_VALID_CONFIG}" --executable "${PDR_CONFIG_CHECK}"
            --report "${PDR_TEST_DIR}/valid-report.json"
    RESULT_VARIABLE valid_result
    OUTPUT_VARIABLE valid_output
    ERROR_VARIABLE valid_error)
if(NOT valid_result EQUAL 0 OR NOT valid_output MATCHES "CONFIG_VALIDATION_OK files=1")
    message(FATAL_ERROR
        "valid configuration was rejected: result=${valid_result}\n${valid_output}\n${valid_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_TOOL}" validate-config
            "${PDR_VALID_CONFIG}" "${override}" --executable "${PDR_CONFIG_CHECK}"
            --report "${PDR_TEST_DIR}/invalid-report.json"
    RESULT_VARIABLE invalid_result
    OUTPUT_VARIABLE invalid_output
    ERROR_VARIABLE invalid_error)
if(NOT invalid_result EQUAL 1)
    message(FATAL_ERROR
        "invalid override was not rejected: result=${invalid_result}\n${invalid_output}\n${invalid_error}")
endif()
foreach(expected "key=osp.web.server.port" "key=pdr.fastdds.domainId"
                 "CONFIG_VALIDATION_FAIL files=2 issues=2")
    if(NOT invalid_error MATCHES "${expected}")
        message(FATAL_ERROR "invalid configuration output missing '${expected}':\n${invalid_error}")
    endif()
endforeach()
