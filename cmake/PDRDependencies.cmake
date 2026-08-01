include(PDRGoogleTest)
include(PDRFastDDS)
include(PDROpenTelemetry)
include(PDRPoco)
include(PDRPahoMqtt)

function(pdr_bootstrap_missing_dependencies)
    if(NOT PDR_AUTO_BOOTSTRAP_DEPENDENCIES)
        return()
    endif()

    set(dependencies_missing FALSE)
    find_package(Poco 1.15.3 CONFIG QUIET COMPONENTS
        Foundation XML JSON Util Net Crypto NetSSL Zip CppParser JWT Data DataSQLite
        PATHS "${PDR_INSTALL_PREFIX}" NO_DEFAULT_PATH)
    if(NOT Poco_FOUND)
        set(dependencies_missing TRUE)
    endif()

    find_package(fastdds 3 CONFIG QUIET
        PATHS "${PDR_INSTALL_PREFIX}" NO_DEFAULT_PATH)
    if(NOT fastdds_FOUND)
        set(dependencies_missing TRUE)
    endif()

    find_package(eclipse-paho-mqtt-c CONFIG QUIET
        PATHS "${PDR_INSTALL_PREFIX}" NO_DEFAULT_PATH)
    if(NOT TARGET eclipse-paho-mqtt-c::paho-mqtt3a-static AND
       NOT TARGET paho-mqtt3a-static)
        set(dependencies_missing TRUE)
    endif()

    if(PDR_ENABLE_OBSERVABILITY)
        find_package(opentelemetry-cpp CONFIG QUIET COMPONENTS exporters_otlp_http
            PATHS "${PDR_INSTALL_PREFIX}" NO_DEFAULT_PATH)
        if(NOT opentelemetry-cpp_FOUND OR NOT TARGET opentelemetry-cpp::otlp_http_metric_exporter)
            set(dependencies_missing TRUE)
        endif()
    endif()

    if(NOT dependencies_missing)
        return()
    endif()

    set(dependency_binary_dir "${PROJECT_SOURCE_DIR}/build/dependencies")
    set(configure_command
        "${CMAKE_COMMAND}"
        -S "${PROJECT_SOURCE_DIR}/cmake"
        -B "${dependency_binary_dir}"
        --fresh
        "-DPDR_DEPENDENCY_INSTALL_PREFIX=${PDR_INSTALL_PREFIX}"
        -DPDR_BUILD_GOOGLETEST=ON)
    if(CMAKE_GENERATOR)
        list(APPEND configure_command -G "${CMAKE_GENERATOR}")
    endif()
    if(CMAKE_GENERATOR_PLATFORM)
        list(APPEND configure_command -A "${CMAKE_GENERATOR_PLATFORM}")
    endif()
    if(CMAKE_GENERATOR_TOOLSET)
        list(APPEND configure_command -T "${CMAKE_GENERATOR_TOOLSET}")
    endif()

    message(STATUS
        "Missing dependencies detected; building them in ${dependency_binary_dir}")
    execute_process(
        COMMAND ${configure_command}
        COMMAND_ECHO STDOUT
        RESULT_VARIABLE dependency_configure_result)
    if(NOT dependency_configure_result EQUAL 0)
        message(FATAL_ERROR
            "Dependency configuration failed with exit code ${dependency_configure_result}")
    endif()

    execute_process(
        COMMAND "${CMAKE_COMMAND}" --build "${dependency_binary_dir}"
            --config Release --parallel 2
        COMMAND_ECHO STDOUT
        RESULT_VARIABLE dependency_build_result)
    if(NOT dependency_build_result EQUAL 0)
        message(FATAL_ERROR
            "Dependency build failed with exit code ${dependency_build_result}")
    endif()

    unset(Poco_DIR CACHE)
    unset(fastdds_DIR CACHE)
    unset(fastcdr_DIR CACHE)
    unset(eclipse-paho-mqtt-c_DIR CACHE)
    unset(opentelemetry-cpp_DIR CACHE)
endfunction()
