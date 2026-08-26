add_library(PDRServiceClientCore src/Client.cpp)
add_library(PocoDDS::ServiceClientCore ALIAS PDRServiceClientCore)
set_target_properties(PDRServiceClientCore PROPERTIES
    EXPORT_NAME ServiceClientCore)
target_include_directories(PDRServiceClientCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRServiceClientCore PUBLIC
    PocoDDS::ServiceDirectoryCore Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRServiceClientCore PUBLIC
        PDR_SERVICE_CLIENT_STATIC)
endif()
pdr_set_warnings(PDRServiceClientCore)

add_library(PDRServiceClientAPI
    src/ProviderRegistry.cpp
    src/RuntimeCoordinator.cpp)
add_library(PocoDDS::ServiceClientAPI ALIAS PDRServiceClientAPI)
set_target_properties(PDRServiceClientAPI PROPERTIES
    EXPORT_NAME ServiceClientAPI)
target_include_directories(PDRServiceClientAPI PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRServiceClientAPI PUBLIC
    PocoDDS::ServiceClientCore
    PocoDDS::ResourceGovernanceAPI
    Poco::OSP
    Poco::Foundation)
target_compile_definitions(PDRServiceClientAPI PUBLIC POCO_NO_AUTOMATIC_LIBS)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRServiceClientAPI PUBLIC
        PDR_SERVICE_CLIENT_STATIC PDR_SERVICE_CLIENT_OSP_STATIC)
endif()
pdr_set_warnings(PDRServiceClientAPI)

add_library(PDRServiceClientTesting STATIC
    testing/src/ProviderConformance.cpp)
add_library(PocoDDS::ServiceClientTesting ALIAS PDRServiceClientTesting)
set_target_properties(PDRServiceClientTesting PROPERTIES
    EXPORT_NAME ServiceClientTesting)
target_include_directories(PDRServiceClientTesting PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/testing/include>
    $<INSTALL_INTERFACE:include>)
target_compile_features(PDRServiceClientTesting PUBLIC cxx_std_17)
target_compile_definitions(PDRServiceClientTesting PUBLIC
    PDR_SERVICE_CLIENT_TESTING_STATIC)
target_link_libraries(PDRServiceClientTesting PUBLIC
    PocoDDS::ServiceClientAPI)
pdr_set_warnings(PDRServiceClientTesting)

if(BUILD_TESTING)
    add_executable(pdr-service-client-smoke tests/ServiceClientSmoke.cpp)
    target_link_libraries(pdr-service-client-smoke PRIVATE
        PocoDDS::ServiceClientCore)
    pdr_set_warnings(pdr-service-client-smoke)
    add_test(NAME service-client-smoke COMMAND pdr-service-client-smoke)
    set_tests_properties(service-client-smoke PROPERTIES
        LABELS "service-client;routing;retry;circuit-breaker;reliability;release")

    add_executable(pdr-service-client-provider-registry-smoke
        tests/ProviderRegistrySmoke.cpp)
    target_link_libraries(pdr-service-client-provider-registry-smoke PRIVATE
        PocoDDS::ServiceClientAPI)
    pdr_set_warnings(pdr-service-client-provider-registry-smoke)
    add_test(NAME service-client-provider-registry-smoke
        COMMAND pdr-service-client-provider-registry-smoke)
    set_tests_properties(service-client-provider-registry-smoke PROPERTIES
        LABELS "service-client;provider;lifecycle;concurrency;release")

    add_executable(pdr-service-client-runtime-coordinator-smoke
        tests/RuntimeCoordinatorSmoke.cpp)
    target_link_libraries(pdr-service-client-runtime-coordinator-smoke PRIVATE
        PocoDDS::ServiceClientAPI)
    pdr_set_warnings(pdr-service-client-runtime-coordinator-smoke)
    add_test(NAME service-client-runtime-coordinator-smoke
        COMMAND pdr-service-client-runtime-coordinator-smoke)
    set_tests_properties(service-client-runtime-coordinator-smoke PROPERTIES
        LABELS "service-client;provider;routing;retry;idempotency;concurrency;recovery;resource-governance;integration;release")

    add_executable(pdr-service-client-provider-conformance-smoke
        tests/ProviderConformanceSmoke.cpp)
    target_link_libraries(pdr-service-client-provider-conformance-smoke
        PRIVATE PocoDDS::ServiceClientTesting)
    pdr_set_warnings(pdr-service-client-provider-conformance-smoke)
    add_test(NAME service-client-provider-conformance-smoke
        COMMAND pdr-service-client-provider-conformance-smoke)
    set_tests_properties(service-client-provider-conformance-smoke PROPERTIES
        LABELS "service-client;provider;conformance;cancellation;deadline;sdk;release")
endif()

install(TARGETS PDRServiceClientCore PDRServiceClientAPI
                PDRServiceClientTesting
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
install(DIRECTORY testing/include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
