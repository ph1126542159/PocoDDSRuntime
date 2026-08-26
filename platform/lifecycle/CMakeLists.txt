add_library(PDRLifecycleCore src/DrainGate.cpp src/Maintenance.cpp)
add_library(PocoDDS::LifecycleCore ALIAS PDRLifecycleCore)
set_target_properties(PDRLifecycleCore PROPERTIES EXPORT_NAME LifecycleCore)
target_include_directories(PDRLifecycleCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRLifecycleCore PUBLIC PDR_LIFECYCLE_STATIC)
endif()
pdr_set_warnings(PDRLifecycleCore)

add_library(PDRLifecyclePersistence src/SqliteMaintenanceStore.cpp)
add_library(PocoDDS::LifecyclePersistence ALIAS PDRLifecyclePersistence)
set_target_properties(PDRLifecyclePersistence PROPERTIES
    EXPORT_NAME LifecyclePersistence)
target_include_directories(PDRLifecyclePersistence PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRLifecyclePersistence PUBLIC
    PocoDDS::LifecycleCore Poco::Data Poco::DataSQLite Poco::JSON Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRLifecyclePersistence PUBLIC PDR_LIFECYCLE_STATIC)
endif()
pdr_set_warnings(PDRLifecyclePersistence)

add_library(PDRLifecycleAPI INTERFACE)
add_library(PocoDDS::LifecycleAPI ALIAS PDRLifecycleAPI)
set_target_properties(PDRLifecycleAPI PROPERTIES EXPORT_NAME LifecycleAPI)
target_include_directories(PDRLifecycleAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRLifecycleAPI INTERFACE
    PocoDDS::LifecycleCore Poco::OSP Poco::Foundation)
target_compile_definitions(PDRLifecycleAPI INTERFACE POCO_NO_AUTOMATIC_LIBS)

target_link_libraries(PDRPlugins INTERFACE PocoDDS::LifecycleAPI)
target_link_libraries(PDRSDK INTERFACE PocoDDS::LifecycleCore)

add_executable(pdr-lifecycle-store tools/MaintenanceStoreTool.cpp)
target_link_libraries(pdr-lifecycle-store PRIVATE
    PocoDDS::LifecyclePersistence Poco::JSON)
pdr_set_warnings(pdr-lifecycle-store)

if(BUILD_TESTING)
    if(NOT Python3_EXECUTABLE)
        find_package(Python3 3.9 QUIET COMPONENTS Interpreter)
    endif()
    add_executable(pdr-drain-gate-smoke tests/DrainGateSmoke.cpp)
    target_link_libraries(pdr-drain-gate-smoke PRIVATE PocoDDS::LifecycleCore)
    pdr_set_warnings(pdr-drain-gate-smoke)
    add_test(NAME drain-gate-smoke COMMAND pdr-drain-gate-smoke)
    set_tests_properties(drain-gate-smoke PROPERTIES
        LABELS "architecture;lifecycle;drain;concurrency;release")

    add_executable(pdr-maintenance-store-smoke tests/MaintenanceStoreSmoke.cpp)
    target_link_libraries(pdr-maintenance-store-smoke PRIVATE
        PocoDDS::LifecyclePersistence)
    pdr_set_warnings(pdr-maintenance-store-smoke)
    add_test(NAME maintenance-store-smoke COMMAND pdr-maintenance-store-smoke)
    set_tests_properties(maintenance-store-smoke PROPERTIES
        LABELS "architecture;lifecycle;persistence;transaction;recovery;release")

    add_executable(pdr-maintenance-journal-seed
        tests/MaintenanceJournalSeed.cpp)
    target_link_libraries(pdr-maintenance-journal-seed PRIVATE
        PocoDDS::LifecyclePersistence)
    pdr_set_warnings(pdr-maintenance-journal-seed)

    if(Python3_EXECUTABLE)
        add_test(NAME lifecycle-store-tool-integration
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_SOURCE_DIR}/tools/runtime_lifecycle_store_integration.py"
                --tool "$<TARGET_FILE:pdr-lifecycle-store>"
                --seed-executable "$<TARGET_FILE:pdr-maintenance-journal-seed>"
                --pdr "${CMAKE_SOURCE_DIR}/tools/pdr.py"
                --workspace "${CMAKE_BINARY_DIR}/runtime-lifecycle-store"
                --path "${PDR_INSTALL_PREFIX}/bin"
                --path "$<TARGET_FILE_DIR:pdr-lifecycle-store>"
                --report "${CMAKE_BINARY_DIR}/reports/runtime-lifecycle-store-integration.json")
        set_tests_properties(lifecycle-store-tool-integration PROPERTIES
            LABELS "architecture;lifecycle;persistence;recovery;operations;negative;release"
            TIMEOUT 60)
    endif()
endif()

install(TARGETS PDRLifecycleCore PDRLifecyclePersistence PDRLifecycleAPI
        pdr-lifecycle-store
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
