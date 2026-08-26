add_library(PDRConfigTransactionAPI INTERFACE)
add_library(PocoDDS::ConfigTransactionAPI ALIAS PDRConfigTransactionAPI)
set_target_properties(PDRConfigTransactionAPI PROPERTIES EXPORT_NAME ConfigTransactionAPI)
target_include_directories(PDRConfigTransactionAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRConfigTransactionAPI INTERFACE Poco::OSP Poco::Foundation)
target_compile_definitions(PDRConfigTransactionAPI INTERFACE POCO_NO_AUTOMATIC_LIBS)

add_library(PDRConfigTransactionCore
    src/ConfigTransaction.cpp
    src/SqliteTransactionStore.cpp
    src/TransactionEngine.cpp)
add_library(PocoDDS::ConfigTransactionCore ALIAS PDRConfigTransactionCore)
set_target_properties(PDRConfigTransactionCore PROPERTIES EXPORT_NAME ConfigTransactionCore)
target_include_directories(PDRConfigTransactionCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRConfigTransactionCore PUBLIC
    PocoDDS::ConfigTransactionAPI
    Poco::Data
    Poco::DataSQLite
    Poco::JSON
    Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRConfigTransactionCore PUBLIC
        PDR_CONFIG_TRANSACTION_STATIC)
endif()
pdr_set_warnings(PDRConfigTransactionCore)

target_link_libraries(PDRPlugins INTERFACE PocoDDS::ConfigTransactionAPI)

if(BUILD_TESTING)
    add_executable(pdr-config-transaction-runtime-smoke
        tests/ConfigTransactionRuntimeSmoke.cpp)
    target_link_libraries(pdr-config-transaction-runtime-smoke PRIVATE
        PocoDDS::ConfigTransactionCore)
    pdr_set_warnings(pdr-config-transaction-runtime-smoke)
    add_test(NAME config-transaction-runtime-smoke
        COMMAND pdr-config-transaction-runtime-smoke)
    set_tests_properties(config-transaction-runtime-smoke PROPERTIES
        LABELS "configuration;transaction;recovery;concurrency;release")

    add_executable(pdr-config-transaction-preflight-smoke
        tests/ConfigTransactionPreflightSmoke.cpp)
    target_link_libraries(pdr-config-transaction-preflight-smoke PRIVATE
        PocoDDS::ConfigTransactionCore)
    pdr_set_warnings(pdr-config-transaction-preflight-smoke)
    add_test(NAME config-transaction-preflight-smoke
        COMMAND pdr-config-transaction-preflight-smoke)
    set_tests_properties(config-transaction-preflight-smoke PROPERTIES
        LABELS "configuration;transaction;preflight;concurrency;fault-injection;recovery;release")

    add_executable(pdr-config-participant-catalog-smoke
        tests/ConfigParticipantCatalogSmoke.cpp)
    target_link_libraries(pdr-config-participant-catalog-smoke PRIVATE
        PocoDDS::ConfigTransactionCore)
    pdr_set_warnings(pdr-config-participant-catalog-smoke)
    add_test(NAME config-participant-catalog-smoke
        COMMAND pdr-config-participant-catalog-smoke)
    set_tests_properties(config-participant-catalog-smoke PROPERTIES
        LABELS "configuration;transaction;dependency;introspection;concurrency;release")

    add_executable(pdr-config-capability-hook-smoke
        tests/ConfigCapabilityHookSmoke.cpp)
    target_link_libraries(pdr-config-capability-hook-smoke PRIVATE
        PocoDDS::ConfigTransactionCore PocoDDS::CapabilitiesCore)
    pdr_set_warnings(pdr-config-capability-hook-smoke)
    add_test(NAME config-capability-hook-smoke
        COMMAND pdr-config-capability-hook-smoke)
    set_tests_properties(config-capability-hook-smoke PROPERTIES
        LABELS "configuration;security;capability;negative;release")

    add_executable(pdr-config-participant-unload-smoke
        tests/ConfigParticipantUnloadSmoke.cpp)
    target_link_libraries(pdr-config-participant-unload-smoke PRIVATE
        PocoDDS::ConfigTransactionCore)
    pdr_set_warnings(pdr-config-participant-unload-smoke)
    add_test(NAME config-participant-unload-smoke
        COMMAND pdr-config-participant-unload-smoke)
    set_tests_properties(config-participant-unload-smoke PROPERTIES
        LABELS "configuration;transaction;concurrency;bundle;lifecycle;release")

    add_executable(pdr-preferences-snapshot-smoke
        tests/PreferencesSnapshotSmoke.cpp)
    target_link_libraries(pdr-preferences-snapshot-smoke PRIVATE Poco::OSP Poco::Util)
    pdr_set_warnings(pdr-preferences-snapshot-smoke)
    add_test(NAME preferences-snapshot-smoke COMMAND pdr-preferences-snapshot-smoke)
    set_tests_properties(preferences-snapshot-smoke PROPERTIES
        LABELS "configuration;concurrency;core")
endif()

install(TARGETS PDRConfigTransactionAPI PDRConfigTransactionCore
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
