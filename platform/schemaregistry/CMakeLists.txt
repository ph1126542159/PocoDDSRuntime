add_library(PDRSchemaRegistryAPI INTERFACE)
add_library(PocoDDS::SchemaRegistryAPI ALIAS PDRSchemaRegistryAPI)
set_target_properties(PDRSchemaRegistryAPI PROPERTIES EXPORT_NAME SchemaRegistryAPI)
target_include_directories(PDRSchemaRegistryAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRSchemaRegistryAPI INTERFACE Poco::OSP Poco::Foundation)
target_compile_definitions(PDRSchemaRegistryAPI INTERFACE POCO_NO_AUTOMATIC_LIBS)

add_library(PDRSchemaRegistryCore
    src/Schema.cpp
    src/SqliteSchemaStore.cpp
    src/Registry.cpp)
add_library(PocoDDS::SchemaRegistryCore ALIAS PDRSchemaRegistryCore)
set_target_properties(PDRSchemaRegistryCore PROPERTIES EXPORT_NAME SchemaRegistryCore)
target_include_directories(PDRSchemaRegistryCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRSchemaRegistryCore PUBLIC
    PocoDDS::SchemaRegistryAPI
    Poco::Data
    Poco::DataSQLite
    Poco::JSON
    Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRSchemaRegistryCore PUBLIC PDR_SCHEMA_REGISTRY_STATIC)
endif()
pdr_set_warnings(PDRSchemaRegistryCore)

target_link_libraries(PDRPlugins INTERFACE PocoDDS::SchemaRegistryAPI)

add_executable(pdr-schema-check tools/SchemaCheck.cpp)
target_link_libraries(pdr-schema-check PRIVATE PocoDDS::SchemaRegistryCore)
pdr_set_warnings(pdr-schema-check)

add_custom_target(pdr-schema-compatibility-gate ALL
    COMMAND $<TARGET_FILE:pdr-schema-check>
        --catalog "${CMAKE_SOURCE_DIR}/contracts/schema-registry/catalog.json"
    DEPENDS pdr-schema-check
    COMMENT "Checking registered schema compatibility")

if(BUILD_TESTING)
    add_executable(pdr-schema-registry-smoke tests/SchemaRegistrySmoke.cpp)
    target_link_libraries(pdr-schema-registry-smoke PRIVATE PocoDDS::SchemaRegistryCore)
    pdr_set_warnings(pdr-schema-registry-smoke)
    add_test(NAME schema-registry-smoke COMMAND pdr-schema-registry-smoke)
    set_tests_properties(schema-registry-smoke PROPERTIES
        LABELS "schema;contract;concurrency;recovery;release")

    add_test(NAME schema-compatibility-gate
        COMMAND pdr-schema-check
            --catalog "${CMAKE_SOURCE_DIR}/contracts/schema-registry/catalog.json")
    set_tests_properties(schema-compatibility-gate PROPERTIES
        LABELS "schema;contract;compatibility;release")

    add_test(NAME schema-compatibility-rejects-breaking-minor
        COMMAND pdr-schema-check
            --baseline "${CMAKE_SOURCE_DIR}/contracts/schema-registry/baselines/pdr.runtime.topic-contract/1.0.0.json"
            --candidate "${CMAKE_CURRENT_SOURCE_DIR}/tests/data/breaking-topic-contract.json")
    set_tests_properties(schema-compatibility-rejects-breaking-minor PROPERTIES
        WILL_FAIL TRUE
        LABELS "schema;contract;compatibility;negative")
endif()

install(TARGETS PDRSchemaRegistryAPI PDRSchemaRegistryCore pdr-schema-check
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
