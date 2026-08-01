if(NOT PDR_CONFIG)
    set(PDR_CONFIG Release)
endif()
if(NOT PDR_DEPENDENCY_PREFIX)
    set(PDR_DEPENDENCY_PREFIX "${PDR_BINARY_DIR}/install")
endif()

set(install_dir "${PDR_BINARY_DIR}/sdk-consumer-install")
set(consumer_build_dir "${PDR_BINARY_DIR}/sdk-consumer-build")

execute_process(
    COMMAND "${CMAKE_COMMAND}" --install "${PDR_BINARY_DIR}"
        --config "${PDR_CONFIG}" --prefix "${install_dir}"
    RESULT_VARIABLE install_result)
if(NOT install_result EQUAL 0)
    message(FATAL_ERROR "SDK install failed: ${install_result}")
endif()

set(configure_command "${CMAKE_COMMAND}"
    -S "${PDR_SOURCE_DIR}/tests/sdk-consumer"
    -B "${consumer_build_dir}"
    -G "${PDR_GENERATOR}"
    "-DCMAKE_PREFIX_PATH=${install_dir};${PDR_DEPENDENCY_PREFIX}"
    "-DPoco_DIR=${PDR_DEPENDENCY_PREFIX}/cmake")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND configure_command -A "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${configure_command} RESULT_VARIABLE configure_result)
if(NOT configure_result EQUAL 0)
    message(FATAL_ERROR "External SDK consumer configure failed: ${configure_result}")
endif()

execute_process(
    COMMAND "${CMAKE_COMMAND}" --build "${consumer_build_dir}"
        --config "${PDR_CONFIG}"
    RESULT_VARIABLE build_result)
if(NOT build_result EQUAL 0)
    message(FATAL_ERROR "External SDK consumer build failed: ${build_result}")
endif()

set(consumer_executable "${consumer_build_dir}/pdr-sdk-consumer")
if(WIN32)
    set(consumer_executable "${consumer_build_dir}/${PDR_CONFIG}/pdr-sdk-consumer.exe")
endif()
execute_process(
    COMMAND "${consumer_executable}"
    RESULT_VARIABLE run_result)
if(NOT run_result EQUAL 0)
    message(FATAL_ERROR "External SDK consumer run failed: ${run_result}")
endif()
