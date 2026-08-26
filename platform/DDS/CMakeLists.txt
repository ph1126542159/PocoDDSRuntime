add_library(PDRFastDDSCore SHARED
    src/EnvelopeTopicDataType.cpp
    src/Runtime.cpp)
add_library(PocoDDS::FastDDSCore ALIAS PDRFastDDSCore)
set_target_properties(PDRFastDDSCore PROPERTIES
    EXPORT_NAME FastDDSCore
    WINDOWS_EXPORT_ALL_SYMBOLS ON)
target_compile_definitions(PDRFastDDSCore PRIVATE PDRFastDDS_EXPORTS)
target_include_directories(PDRFastDDSCore
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRFastDDSCore PUBLIC fastdds)
target_link_libraries(PDRFastDDSCore PRIVATE Poco::Foundation)
if(PDR_ENABLE_OBSERVABILITY)
    target_include_directories(PDRFastDDSCore PRIVATE
        $<TARGET_PROPERTY:PDRObservability,INTERFACE_INCLUDE_DIRECTORIES>)
    target_link_libraries(PDRFastDDSCore PRIVATE
        $<TARGET_LINKER_FILE:PDRObservability>)
    add_dependencies(PDRFastDDSCore PDRObservability)
    target_compile_definitions(PDRFastDDSCore PRIVATE PDR_ENABLE_OBSERVABILITY=1)
endif()
pdr_isolate_embedded_static_dependencies(PDRFastDDSCore)
pdr_set_warnings(PDRFastDDSCore)

add_library(PDRFastDDSAbiV1 SHARED
    src/AbiV1.cpp)
add_library(PocoDDS::FastDDSAbiV1 ALIAS PDRFastDDSAbiV1)
set_target_properties(PDRFastDDSAbiV1 PROPERTIES
    EXPORT_NAME FastDDSAbiV1
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES)
target_include_directories(PDRFastDDSAbiV1
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_features(PDRFastDDSAbiV1 PRIVATE cxx_std_17)
target_link_libraries(PDRFastDDSAbiV1 PRIVATE PocoDDS::FastDDSCore)
pdr_set_warnings(PDRFastDDSAbiV1)

add_library(PDRFastDDS SHARED
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
        PocoDDS::FastDDSCore
        PocoDDS::DeviceCore)
if(PDR_ENABLE_OBSERVABILITY)
    target_link_libraries(PDRFastDDS PUBLIC PocoDDS::Observability)
    target_compile_definitions(PDRFastDDS PUBLIC PDR_ENABLE_OBSERVABILITY=1)
endif()

pdr_isolate_embedded_static_dependencies(PDRFastDDS)

pdr_set_warnings(PDRFastDDS)

if(BUILD_TESTING)
    file(SHA256
        "${CMAKE_SOURCE_DIR}/config/fastdds-deployment.properties.example"
        pdr_fastdds_example_sha256)
    add_custom_command(TARGET PDRFastDDS POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${PDR_TEST_OUTPUT_DIRECTORY}"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:PDRFastDDS>"
            "${PDR_TEST_OUTPUT_DIRECTORY}/$<TARGET_FILE_NAME:PDRFastDDS>")
endif()

add_executable(pdr-fastdds-device-smoke
    tests/DeviceSmoke.cpp)
target_link_libraries(pdr-fastdds-device-smoke PRIVATE PocoDDS::FastDDS)
target_link_libraries(pdr-fastdds-device-smoke PRIVATE PocoDDS::SimulationDevice)
pdr_set_warnings(pdr-fastdds-device-smoke)

add_executable(pdr-fastdds-profile-check
    tools/FastDdsProfileCheck.cpp)
target_link_libraries(pdr-fastdds-profile-check PRIVATE PocoDDS::FastDDSCore)
pdr_set_warnings(pdr-fastdds-profile-check)

if(BUILD_TESTING)
    add_executable(pdr-fastdds-runtime-snapshot-smoke tests/RuntimeSnapshotSmoke.cpp)
    target_link_libraries(pdr-fastdds-runtime-snapshot-smoke PRIVATE PocoDDS::FastDDS)
    pdr_set_warnings(pdr-fastdds-runtime-snapshot-smoke)
    add_test(NAME fastdds-runtime-snapshot-smoke COMMAND pdr-fastdds-runtime-snapshot-smoke)
    if(WIN32)
        set_tests_properties(fastdds-runtime-snapshot-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()

    add_executable(pdr-fastdds-abi-v1-smoke tests/AbiV1Smoke.cpp)
    target_link_libraries(pdr-fastdds-abi-v1-smoke PRIVATE PocoDDS::FastDDSAbiV1)
    pdr_set_warnings(pdr-fastdds-abi-v1-smoke)
    add_test(NAME fastdds-abi-v1-smoke COMMAND pdr-fastdds-abi-v1-smoke)
    set_tests_properties(fastdds-abi-v1-smoke PROPERTIES
        LABELS "fastdds;abi;contract;integration"
        PASS_REGULAR_EXPRESSION
            "FAST_DDS_ABI_V1_PASS version=1 lifecycle=verified callback=verified unsubscribe=verified drain=verified"
        TIMEOUT 15)
    if(WIN32)
        set_tests_properties(fastdds-abi-v1-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
        get_filename_component(pdr_fastdds_linker_directory "${CMAKE_LINKER}" DIRECTORY)
        find_program(PDR_FASTDDS_DUMPBIN_EXECUTABLE NAMES dumpbin
            HINTS "${pdr_fastdds_linker_directory}")
        if(NOT PDR_FASTDDS_DUMPBIN_EXECUTABLE)
            message(FATAL_ERROR "PDRFastDDSAbiV1 export testing requires dumpbin")
        endif()
        add_test(NAME fastdds-abi-v1-exports
            COMMAND "${CMAKE_COMMAND}"
                -DPDR_FASTDDS_ABI_LIBRARY=$<TARGET_FILE:PDRFastDDSAbiV1>
                -DPDR_DUMPBIN=${PDR_FASTDDS_DUMPBIN_EXECUTABLE}
                -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/RunFastDdsAbiV1Exports.cmake")
        set_tests_properties(fastdds-abi-v1-exports PROPERTIES
            LABELS "fastdds;abi;contract;unit"
            PASS_REGULAR_EXPRESSION "FAST_DDS_ABI_V1_EXPORTS_PASS symbols=12")
    endif()

    add_test(NAME fastdds-profile-check-integrity
        COMMAND pdr-fastdds-profile-check
            --profile "${CMAKE_SOURCE_DIR}/config/fastdds-deployment.properties.example"
            --sha256 "${pdr_fastdds_example_sha256}")
    set_tests_properties(fastdds-profile-check-integrity PROPERTIES
        LABELS "configuration;fastdds;contract;integration;security"
        PASS_REGULAR_EXPRESSION "integrity=sha256")
    if(WIN32)
        set_tests_properties(fastdds-profile-check-integrity PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()
    add_test(NAME fastdds-device-smoke COMMAND pdr-fastdds-device-smoke)
    if(WIN32)
        set_tests_properties(fastdds-device-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()

    add_test(NAME fastdds-profile-check-example
        COMMAND pdr-fastdds-profile-check
            --profile "${CMAKE_SOURCE_DIR}/config/fastdds-deployment.properties.example")
    set_tests_properties(fastdds-profile-check-example PROPERTIES
        LABELS "configuration;fastdds;contract;integration"
        PASS_REGULAR_EXPRESSION
            "PDR_FASTDDS_PROFILE_CHECK_PASS configured=true transport=UDPv4")
    if(WIN32)
        set_tests_properties(fastdds-profile-check-example PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()

    add_test(NAME fastdds-profile-check-invalid
        COMMAND "${CMAKE_COMMAND}"
            -DPDR_FASTDDS_PROFILE_CHECK=$<TARGET_FILE:pdr-fastdds-profile-check>
            -DPDR_FASTDDS_INVALID_PROFILE=${CMAKE_CURRENT_SOURCE_DIR}/tests/data/invalid-fastdds-deployment.properties
            "-DPDR_FASTDDS_EXPECTED_ERROR=initialPeers are required when builtin multicast is disabled"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/RunFastDdsProfileCheckFailure.cmake")
    set_tests_properties(fastdds-profile-check-invalid PROPERTIES
        LABELS "configuration;fastdds;contract;fault-injection")

    add_test(NAME fastdds-profile-check-integrity-mismatch
        COMMAND "${CMAKE_COMMAND}"
            -DPDR_FASTDDS_PROFILE_CHECK=$<TARGET_FILE:pdr-fastdds-profile-check>
            -DPDR_FASTDDS_INVALID_PROFILE=${CMAKE_SOURCE_DIR}/config/fastdds-deployment.properties.example
            -DPDR_FASTDDS_EXPECTED_SHA256=0000000000000000000000000000000000000000000000000000000000000000
            "-DPDR_FASTDDS_EXPECTED_ERROR=Fast DDS deployment profile SHA-256 mismatch"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/RunFastDdsProfileCheckFailure.cmake")
    set_tests_properties(fastdds-profile-check-integrity-mismatch PROPERTIES
        LABELS "configuration;fastdds;contract;fault-injection;security")
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
install(TARGETS PDRFastDDSCore EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(TARGETS PDRFastDDSAbiV1 EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(TARGETS pdr-fastdds-profile-check
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
