add_library(PDRFastDDS SHARED
    src/EnvelopeTopicDataType.cpp
    src/Runtime.cpp
    src/DeviceBridge.cpp
    src/ServiceEndpoint.cpp)
add_library(PocoDDS::FastDDS ALIAS PDRFastDDS)

set_target_properties(PDRFastDDS PROPERTIES
    WINDOWS_EXPORT_ALL_SYMBOLS ON)

target_include_directories(PDRFastDDS
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)

target_link_libraries(PDRFastDDS
    PUBLIC
        PocoDDS::Devices
        fastdds)
if(PDR_ENABLE_OBSERVABILITY)
    target_link_libraries(PDRFastDDS PUBLIC PocoDDS::Observability)
    target_compile_definitions(PDRFastDDS PUBLIC PDR_ENABLE_OBSERVABILITY=1)
endif()

pdr_isolate_embedded_static_dependencies(PDRFastDDS)

pdr_set_warnings(PDRFastDDS)

if(BUILD_TESTING)
    add_custom_command(TARGET PDRFastDDS POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${PDR_TEST_OUTPUT_DIRECTORY}"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:PDRFastDDS>"
            "${PDR_TEST_OUTPUT_DIRECTORY}/$<TARGET_FILE_NAME:PDRFastDDS>")
endif()

add_executable(pdr-fastdds-device-smoke
    tests/DeviceSmoke.cpp)
target_link_libraries(pdr-fastdds-device-smoke PRIVATE PocoDDS::FastDDS)
pdr_set_warnings(pdr-fastdds-device-smoke)
if(BUILD_TESTING)
    add_test(NAME fastdds-device-smoke COMMAND pdr-fastdds-device-smoke)
    if(WIN32)
        set_tests_properties(fastdds-device-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()
endif()

add_executable(pdr-service-integration-smoke
    tests/ServiceIntegrationSmoke.cpp)
target_link_libraries(pdr-service-integration-smoke
    PRIVATE PocoDDS::FastDDS Poco::JSON Poco::Foundation)
pdr_set_warnings(pdr-service-integration-smoke)

if(PDR_ENABLE_OBSERVABILITY)
    add_executable(pdr-business-trace-probe
        tests/BusinessTraceProbe.cpp)
    target_link_libraries(pdr-business-trace-probe
        PRIVATE PocoDDS::FastDDS PocoDDS::Observability)
    pdr_set_warnings(pdr-business-trace-probe)
endif()

install(TARGETS PDRFastDDS
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
