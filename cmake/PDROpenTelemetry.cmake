include_guard(GLOBAL)

function(pdr_require_opentelemetry)
    # Protobuf 35 exports utf8_range in its public link interface, but the
    # OpenTelemetry package does not load that package transitively.
    find_package(utf8_range CONFIG QUIET PATHS "${PDR_INSTALL_PREFIX}")
    # Load the config packages before OpenTelemetry. Otherwise CMake's legacy
    # FindProtobuf module can create a reduced protobuf::libprotobuf target
    # that omits the full Abseil static link interface on Windows.
    find_package(absl CONFIG REQUIRED PATHS "${PDR_INSTALL_PREFIX}")
    find_package(Protobuf CONFIG REQUIRED PATHS "${PDR_INSTALL_PREFIX}")
    find_package(opentelemetry-cpp CONFIG QUIET COMPONENTS exporters_otlp_http
        PATHS "${PDR_INSTALL_PREFIX}")
    if(opentelemetry-cpp_FOUND AND TARGET opentelemetry-cpp::otlp_http_metric_exporter)
        return()
    endif()
    message(FATAL_ERROR
        "OpenTelemetry was requested but is not installed. Build the dependency superbuild "
        "in build/dependencies.")
endfunction()
