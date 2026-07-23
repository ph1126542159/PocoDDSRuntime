find_package(opentelemetry-cpp 1.28.0 CONFIG QUIET)
if(opentelemetry-cpp_FOUND)
    message(STATUS "Using existing OpenTelemetry C++")
    return()
endif()

ExternalProject_Add(opentelemetry
    GIT_REPOSITORY https://github.com/open-telemetry/opentelemetry-cpp.git
    GIT_TAG v1.28.0 GIT_SHALLOW TRUE
    GIT_SUBMODULES ""
    CMAKE_ARGS ${PDR_DEPENDENCY_CMAKE_ARGS}
        -DBUILD_TESTING=OFF -DWITH_OTLP_GRPC=OFF
        -DWITH_OTLP_HTTP=OFF -DWITH_OTLP_FILE=OFF -DWITH_EXAMPLES=OFF
        -DWITH_ELASTICSEARCH=OFF -DWITH_ZIPKIN=OFF -DWITH_ETW=OFF
        -DWITH_CONFIGURATION=OFF -DBUILD_W3CTRACECONTEXT_TEST=OFF)
