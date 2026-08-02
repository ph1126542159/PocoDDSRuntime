foreach(required PDR_CMAKE PDR_CTEST PDR_PYTHON PDR_SOURCE_DIR PDR_BINARY_DIR
                 PDR_CONFIG PDR_GENERATOR PDR_DEPENDENCY_PREFIX)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR "RunGeneratedDeviceTest.cmake requires ${required}")
    endif()
endforeach()

set(root "${PDR_BINARY_DIR}/generated-device-consumer")
set(module_root "${root}/source")
set(module "${module_root}/ExampleDevice")
set(install "${root}/install")
set(report "${root}/verify-report.json")
file(REMOVE_RECURSE "${root}")

execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/pdr.py"
            new device ExampleDevice --output "${module_root}"
    RESULT_VARIABLE generate_result)
if(NOT generate_result EQUAL 0)
    message(FATAL_ERROR "Device template generation failed: ${generate_result}")
endif()

execute_process(
    COMMAND "${PDR_CMAKE}" --install "${PDR_BINARY_DIR}"
            --config "${PDR_CONFIG}" --prefix "${install}"
    RESULT_VARIABLE install_result)
if(NOT install_result EQUAL 0)
    message(FATAL_ERROR "Framework install for generated device failed: ${install_result}")
endif()

set(verify_command "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/pdr.py"
    verify "${module}"
    --cmake "${PDR_CMAKE}"
    --ctest "${PDR_CTEST}"
    --generator "${PDR_GENERATOR}"
    --config "${PDR_CONFIG}"
    --prefix "${install}"
    --prefix "${PDR_DEPENDENCY_PREFIX}"
    --report "${report}")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND verify_command --platform "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(
    COMMAND ${verify_command}
    RESULT_VARIABLE verify_result)
if(NOT verify_result EQUAL 0)
    message(FATAL_ERROR "Generated device verification failed: ${verify_result}; report=${report}")
endif()
