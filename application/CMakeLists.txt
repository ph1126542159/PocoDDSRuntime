add_library(PDRApplication INTERFACE)
add_library(PocoDDS::Application ALIAS PDRApplication)
set_target_properties(PDRApplication PROPERTIES EXPORT_NAME Application)

target_include_directories(PDRApplication INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)

if(PDR_ENABLE_OBSERVABILITY)
    # Observability instrumentation is a build-profile enhancement, not part of
    # the stable installed Application API. External SDK consumers therefore do
    # not inherit the optional OpenTelemetry implementation dependency.
    target_link_libraries(PDRApplication INTERFACE
        $<BUILD_INTERFACE:PocoDDS::Observability>)
    target_compile_definitions(PDRApplication INTERFACE
        $<BUILD_INTERFACE:PDR_ENABLE_OBSERVABILITY=1>)
endif()

if(BUILD_TESTING)
    add_executable(pdr-application-smoke tests/ApplicationSmoke.cpp)
    target_link_libraries(pdr-application-smoke PRIVATE PocoDDS::Application)
    pdr_set_warnings(pdr-application-smoke)
    add_test(NAME application-smoke COMMAND pdr-application-smoke)
    if(WIN32)
        set_tests_properties(application-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()
endif()

install(TARGETS PDRApplication EXPORT PocoDDSRuntimeTargets)
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
