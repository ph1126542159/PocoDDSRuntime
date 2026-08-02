option(PDR_FORCE_OPENTELEMETRY_REBUILD
    "Reconfigure and rebuild OpenTelemetry even when it is installed" OFF)
if(NOT PDR_FORCE_OPENTELEMETRY_REBUILD)
    find_package(opentelemetry-cpp 1.28.0 CONFIG QUIET COMPONENTS exporters_otlp_http)
    if(opentelemetry-cpp_FOUND AND TARGET opentelemetry-cpp::otlp_http_metric_exporter)
        message(STATUS "Using existing OpenTelemetry C++ with OTLP/HTTP")
        return()
    endif()
endif()

ExternalProject_Add(opentelemetry
    GIT_REPOSITORY https://github.com/open-telemetry/opentelemetry-cpp.git
    GIT_TAG v1.28.0 GIT_SHALLOW TRUE
    GIT_SUBMODULES ""
    CMAKE_ARGS ${PDR_DEPENDENCY_CMAKE_ARGS}
        -DBUILD_TESTING=OFF -DWITH_OTLP_GRPC=OFF
        -DWITH_OTLP_HTTP=ON -DWITH_OTLP_FILE=OFF -DWITH_EXAMPLES=OFF
        -DWITH_BENCHMARK=OFF -DWITH_FUNC_TESTS=OFF
        -DCMAKE_CXX_STANDARD=17 -DCMAKE_CXX_STANDARD_REQUIRED=ON
        -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL
        -Dprotobuf_MSVC_STATIC_RUNTIME=OFF -DABSL_MSVC_STATIC_RUNTIME=OFF
        -DABSL_PROPAGATE_CXX_STD=ON
        -DCMAKE_DISABLE_FIND_PACKAGE_Protobuf=ON
        -DCMAKE_DISABLE_FIND_PACKAGE_absl=ON
        -DWITH_ELASTICSEARCH=OFF -DWITH_ZIPKIN=OFF -DWITH_ETW=OFF
        -DWITH_CONFIGURATION=OFF -DBUILD_W3CTRACECONTEXT_TEST=OFF
    # Fetched Protobuf and Abseil are not part of OpenTelemetry's top-level
    # install manifest. Install all three from the same build tree so a stale
    # standalone Protobuf cannot leave an ABI-incompatible mixed prefix.
    INSTALL_COMMAND
        "${CMAKE_COMMAND}" --install <BINARY_DIR>/_deps/absl-build --config Release
        COMMAND "${CMAKE_COMMAND}" --build <BINARY_DIR>/_deps/protobuf-build
                --config Release --target libprotoc protoc
                protoc-gen-upb protoc-gen-upbdefs protoc-gen-upb_minitable
                --parallel 2
        COMMAND "${CMAKE_COMMAND}" --install <BINARY_DIR>/_deps/protobuf-build
                --config Release --component libprotobuf-lite
        COMMAND "${CMAKE_COMMAND}" --install <BINARY_DIR>/_deps/protobuf-build
                --config Release --component libprotobuf
        COMMAND "${CMAKE_COMMAND}" --install <BINARY_DIR>/_deps/protobuf-build
                --config Release --component libprotoc
        COMMAND "${CMAKE_COMMAND}" --install <BINARY_DIR>/_deps/protobuf-build
                --config Release --component libupb
        COMMAND "${CMAKE_COMMAND}" --install <BINARY_DIR>/_deps/protobuf-build
                --config Release --component protoc
        COMMAND "${CMAKE_COMMAND}" --install <BINARY_DIR>/_deps/protobuf-build
                --config Release --component protobuf-headers
        COMMAND "${CMAKE_COMMAND}" --install <BINARY_DIR>/_deps/protobuf-build
                --config Release --component protobuf-export
        COMMAND "${CMAKE_COMMAND}" --install <BINARY_DIR>/_deps/protobuf-build
                --config Release --component Unspecified
        COMMAND "${CMAKE_COMMAND}" --install <BINARY_DIR> --config Release)
