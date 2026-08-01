foreach(required PDR_CMAKE PDR_CTEST PDR_PYTHON PDR_SOURCE_DIR PDR_BINARY_DIR
                 PDR_CONFIG PDR_GENERATOR PDR_DEPENDENCY_PREFIX)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR "RunGeneratedDeviceTest.cmake requires ${required}")
    endif()
endforeach()

set(root "${PDR_BINARY_DIR}/generated-device-consumer")
set(module_root "${root}/source")
set(module "${module_root}/ExampleDevice")
set(build "${root}/build")
set(install "${root}/install")
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

set(configure_command "${PDR_CMAKE}"
    -S "${module}" -B "${build}" -G "${PDR_GENERATOR}"
    "-DCMAKE_PREFIX_PATH=${install};${PDR_DEPENDENCY_PREFIX}"
    "-DPoco_DIR=${PDR_DEPENDENCY_PREFIX}/cmake")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND configure_command -A "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${configure_command} RESULT_VARIABLE configure_result)
if(NOT configure_result EQUAL 0)
    message(FATAL_ERROR "Generated device configure failed: ${configure_result}")
endif()

execute_process(
    COMMAND "${PDR_CMAKE}" --build "${build}" --config "${PDR_CONFIG}"
    RESULT_VARIABLE build_result)
if(NOT build_result EQUAL 0)
    message(FATAL_ERROR "Generated device build failed: ${build_result}")
endif()

execute_process(
    COMMAND "${PDR_CTEST}" --test-dir "${build}"
            -C "${PDR_CONFIG}" --output-on-failure
    RESULT_VARIABLE test_result)
if(NOT test_result EQUAL 0)
    message(FATAL_ERROR "Generated device smoke failed: ${test_result}")
endif()
