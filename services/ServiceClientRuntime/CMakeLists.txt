add_library(PDRServiceClientTraceAdapter STATIC
    src/InvocationTraceAdapter.cpp)
target_include_directories(PDRServiceClientTraceAdapter
    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_features(PDRServiceClientTraceAdapter PUBLIC cxx_std_17)
target_link_libraries(PDRServiceClientTraceAdapter
    PUBLIC PocoDDS::ServiceClientAPI PocoDDS::Observability)
pdr_set_warnings(PDRServiceClientTraceAdapter)

add_library(PDRServiceClientJournalAdapter STATIC
    src/SqliteInvocationJournal.cpp)
target_include_directories(PDRServiceClientJournalAdapter
    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_features(PDRServiceClientJournalAdapter PUBLIC cxx_std_17)
target_link_libraries(PDRServiceClientJournalAdapter
    PUBLIC
        PocoDDS::ServiceClientAPI
        Poco::Data
        Poco::DataSQLite
        Poco::JSON
        Poco::Foundation)
pdr_set_warnings(PDRServiceClientJournalAdapter)

myiot_add_osp_bundle(PDR_ServiceClientRuntime_Bundle
    "pdr.service.serviceClientRuntime"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::ServiceClientAPI
        PDRServiceClientTraceAdapter
        PDRServiceClientJournalAdapter
        PocoDDS::ServiceDirectoryAPI
        PocoDDS::ResourceGovernanceAPI
        PocoDDS::CapabilitiesAPI
        PocoDDS::Health
        PocoDDS::Observability
        PocoDDS::Security
        Poco::OSPWeb
        Poco::OSP
        Poco::JSON
        Poco::Net
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS
        ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
        ${CMAKE_SOURCE_DIR}/platform/OSP/ManagementAuth/include
        ${CMAKE_SOURCE_DIR}/platform/capabilities/include
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/ServiceClientRuntime.bndlspec)
pdr_set_warnings(PDR_ServiceClientRuntime_Bundle)

if(BUILD_TESTING)
    add_executable(pdr-service-client-invocation-trace-smoke
        tests/InvocationTraceAdapterSmoke.cpp)
    target_link_libraries(pdr-service-client-invocation-trace-smoke
        PRIVATE PDRServiceClientTraceAdapter PocoDDS::Observability)
    pdr_set_warnings(pdr-service-client-invocation-trace-smoke)
    add_test(NAME service-client-invocation-trace-smoke
        COMMAND pdr-service-client-invocation-trace-smoke)
    set_tests_properties(service-client-invocation-trace-smoke PROPERTIES
        LABELS "service-client;audit;trace;observability;concurrency;integration")

    add_executable(pdr-service-client-invocation-journal-smoke
        tests/SqliteInvocationJournalSmoke.cpp)
    target_link_libraries(pdr-service-client-invocation-journal-smoke
        PRIVATE PDRServiceClientJournalAdapter)
    pdr_set_warnings(pdr-service-client-invocation-journal-smoke)
    add_test(NAME service-client-invocation-journal-smoke
        COMMAND pdr-service-client-invocation-journal-smoke)
    set_tests_properties(service-client-invocation-journal-smoke PROPERTIES
        LABELS "service-client;idempotency;sqlite;persistence;recovery;integration")
    if(WIN32)
        set_tests_properties(service-client-invocation-trace-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
        set_tests_properties(service-client-invocation-journal-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()
endif()
