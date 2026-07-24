add_library(PDRObservability SHARED
    src/BusinessTracer.cpp
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
        opentelemetry-cpp::resources
        Poco::DataSQLite
        Poco::Data
        Poco::Net
        Poco::JSON
        Poco::Foundation)
pdr_set_warnings(PDRObservability)

if(BUILD_TESTING)
    add_executable(pdr-business-tracing-test tests/BusinessTracingTest.cpp)
    target_link_libraries(pdr-business-tracing-test
        PRIVATE PocoDDS::Observability Poco::Foundation)
    pdr_set_warnings(pdr-business-tracing-test)
    add_test(NAME business-tracing COMMAND pdr-business-tracing-test)
    if(WIN32)
        set_tests_properties(business-tracing PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()
endif()

install(TARGETS PDRObservability
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
