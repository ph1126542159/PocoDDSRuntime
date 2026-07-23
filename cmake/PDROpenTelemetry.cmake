include_guard(GLOBAL)

function(pdr_require_opentelemetry)
    find_package(opentelemetry-cpp CONFIG QUIET PATHS "${PDR_INSTALL_PREFIX}")
    if(opentelemetry-cpp_FOUND)
        return()
    endif()
    message(FATAL_ERROR
        "OpenTelemetry was requested but is not installed. Build the dependency superbuild "
        "in build/dependencies.")
endfunction()
