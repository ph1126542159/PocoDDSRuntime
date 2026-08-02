add_library(PDRObservability SHARED
    src/BusinessTracer.cpp
    src/Metrics.cpp
    src/OtlpHttpJsonExporter.cpp
    src/TraceHttpServer.cpp
    src/TraceSerialization.cpp
    src/TraceStore.cpp)
add_library(PocoDDS::Observability ALIAS PDRObservability)
target_compile_definitions(PDRObservability PRIVATE PDRObservability_EXPORTS)

set_target_properties(PDRObservability PROPERTIES
    WINDOWS_EXPORT_ALL_SYMBOLS ON)

target_include_directories(PDRObservability
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE src)

target_link_libraries(PDRObservability
    PUBLIC opentelemetry-cpp::api
    PRIVATE
        opentelemetry-cpp::trace
        opentelemetry-cpp::metrics
        opentelemetry-cpp::resources
        opentelemetry-cpp::otlp_http_metric_exporter
        # The static OTLP package keeps protobuf behind a LINK_ONLY edge on
        # Windows. Link it explicitly so its complete Abseil interface reaches
        # this shared-library link step.
        protobuf::libprotobuf
        Poco::DataSQLite
        Poco::Data
        Poco::Net
        Poco::NetSSL
        Poco::Crypto
        Poco::JSON
        Poco::Foundation)
pdr_set_warnings(PDRObservability)

if(BUILD_TESTING)
    add_custom_command(TARGET PDRObservability POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${PDR_TEST_OUTPUT_DIRECTORY}"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:PDRObservability>" "${PDR_TEST_OUTPUT_DIRECTORY}/$<TARGET_FILE_NAME:PDRObservability>")
    add_executable(pdr-business-tracing-test tests/BusinessTracingTest.cpp)
    target_link_libraries(pdr-business-tracing-test
        PRIVATE PocoDDS::Observability Poco::Foundation)
    pdr_set_warnings(pdr-business-tracing-test)
    add_test(NAME business-tracing COMMAND pdr-business-tracing-test)
    add_executable(pdr-metrics-test tests/MetricsTest.cpp)
    target_link_libraries(pdr-metrics-test
        PRIVATE PocoDDS::Observability Poco::Net Poco::Foundation)
    pdr_set_warnings(pdr-metrics-test)
    add_test(NAME metrics COMMAND pdr-metrics-test)
    if(WIN32)
        set_tests_properties(business-tracing metrics PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()
endif()

install(TARGETS PDRObservability
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
