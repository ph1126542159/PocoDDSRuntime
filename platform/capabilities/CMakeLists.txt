add_library(PDRCapabilitiesAPI INTERFACE)
add_library(PocoDDS::CapabilitiesAPI ALIAS PDRCapabilitiesAPI)
set_target_properties(PDRCapabilitiesAPI PROPERTIES EXPORT_NAME CapabilitiesAPI)
target_include_directories(PDRCapabilitiesAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRCapabilitiesAPI INTERFACE Poco::OSP Poco::Foundation)
target_compile_definitions(PDRCapabilitiesAPI INTERFACE POCO_NO_AUTOMATIC_LIBS)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRCapabilitiesAPI INTERFACE PDR_CAPABILITIES_STATIC)
endif()

add_library(PDRCapabilitiesCore
    src/Capabilities.cpp
    src/PolicyEngine.cpp
    src/DecisionLease.cpp
    src/AuthorizedTransport.cpp)
add_library(PocoDDS::CapabilitiesCore ALIAS PDRCapabilitiesCore)
set_target_properties(PDRCapabilitiesCore PROPERTIES EXPORT_NAME CapabilitiesCore)
target_include_directories(PDRCapabilitiesCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRCapabilitiesCore PUBLIC
    PocoDDS::CapabilitiesAPI
    PocoDDS::RuntimeCore
    Poco::JSON
    Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRCapabilitiesCore PUBLIC PDR_CAPABILITIES_STATIC)
endif()
pdr_set_warnings(PDRCapabilitiesCore)

add_library(PDRCapabilitiesPersistence src/SqlitePolicyStore.cpp)
add_library(PocoDDS::CapabilitiesPersistence ALIAS PDRCapabilitiesPersistence)
set_target_properties(PDRCapabilitiesPersistence PROPERTIES
    EXPORT_NAME CapabilitiesPersistence)
target_include_directories(PDRCapabilitiesPersistence PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRCapabilitiesPersistence PUBLIC
    PocoDDS::CapabilitiesCore
    Poco::Data
    Poco::DataSQLite
    Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRCapabilitiesPersistence PUBLIC PDR_CAPABILITIES_STATIC)
endif()
pdr_set_warnings(PDRCapabilitiesPersistence)

target_link_libraries(PDRPlugins INTERFACE PocoDDS::CapabilitiesAPI)

add_executable(pdr-capability-check tools/CapabilityCheck.cpp)
target_link_libraries(pdr-capability-check PRIVATE PocoDDS::CapabilitiesCore Poco::JSON)
pdr_set_warnings(pdr-capability-check)

add_executable(pdr-capability-store-check tools/CapabilityStoreCheck.cpp)
target_link_libraries(pdr-capability-store-check PRIVATE
    PocoDDS::CapabilitiesPersistence Poco::JSON)
pdr_set_warnings(pdr-capability-store-check)

add_executable(pdr-capability-store-apply tools/CapabilityStoreApply.cpp)
target_link_libraries(pdr-capability-store-apply PRIVATE
    PocoDDS::CapabilitiesPersistence Poco::JSON)
pdr_set_warnings(pdr-capability-store-apply)

add_custom_target(pdr-capability-policy-gate ALL
    COMMAND $<TARGET_FILE:pdr-capability-check>
        --policy "${CMAKE_SOURCE_DIR}/contracts/capabilities/default-policy.json"
        --validate
    DEPENDS pdr-capability-check
    COMMENT "Validating default-deny Bundle capability policy")

file(MAKE_DIRECTORY "${PDR_RUNTIME_PROCESS_DIRECTORY}/config")
configure_file(
    "${CMAKE_SOURCE_DIR}/contracts/capabilities/default-policy.json"
    "${PDR_RUNTIME_PROCESS_DIRECTORY}/config/pdr-capability-policy.json"
    COPYONLY)

if(BUILD_TESTING)
    add_executable(pdr-capabilities-smoke tests/CapabilitiesSmoke.cpp)
    target_link_libraries(pdr-capabilities-smoke PRIVATE
        PocoDDS::CapabilitiesCore PocoDDS::RuntimeCore)
    pdr_set_warnings(pdr-capabilities-smoke)
    add_test(NAME capabilities-smoke COMMAND pdr-capabilities-smoke)
    set_tests_properties(capabilities-smoke PROPERTIES
        LABELS "security;capability;authorization;concurrency;negative;release")

    add_test(NAME capability-policy-gate
        COMMAND pdr-capability-check
            --policy "${CMAKE_SOURCE_DIR}/contracts/capabilities/default-policy.json"
            --validate)
    set_tests_properties(capability-policy-gate PROPERTIES
        LABELS "security;capability;contract;release")

    add_test(NAME capability-default-deny
        COMMAND pdr-capability-check
            --policy "${CMAKE_SOURCE_DIR}/contracts/capabilities/default-policy.json"
            --principal untrusted.bundle
            --resource-kind topic
            --resource pdr.runtime.events
            --action publish)
    set_tests_properties(capability-default-deny PROPERTIES
        WILL_FAIL TRUE LABELS "security;capability;negative")

    add_executable(pdr-capability-persistence-smoke
        tests/CapabilityPersistenceSmoke.cpp)
    target_link_libraries(pdr-capability-persistence-smoke PRIVATE
        PocoDDS::CapabilitiesPersistence Poco::Data Poco::DataSQLite)
    pdr_set_warnings(pdr-capability-persistence-smoke)
    add_test(NAME capability-persistence-smoke
        COMMAND pdr-capability-persistence-smoke)
    set_tests_properties(capability-persistence-smoke PROPERTIES
        LABELS "security;capability;persistence;recovery;transaction;negative;release")

    add_executable(pdr-decision-lease-smoke tests/DecisionLeaseSmoke.cpp)
    target_link_libraries(pdr-decision-lease-smoke PRIVATE
        PocoDDS::CapabilitiesCore PocoDDS::RuntimeCore)
    pdr_set_warnings(pdr-decision-lease-smoke)
    add_test(NAME decision-lease-smoke COMMAND pdr-decision-lease-smoke)
    set_tests_properties(decision-lease-smoke PROPERTIES
        LABELS "security;capability;performance;concurrency;recovery;negative;release")
endif()

install(TARGETS PDRCapabilitiesAPI PDRCapabilitiesCore PDRCapabilitiesPersistence
        pdr-capability-check pdr-capability-store-check pdr-capability-store-apply
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
install(FILES "${CMAKE_SOURCE_DIR}/contracts/capabilities/default-policy.json"
    DESTINATION "${CMAKE_INSTALL_BINDIR}/config"
    RENAME "pdr-capability-policy.json")
