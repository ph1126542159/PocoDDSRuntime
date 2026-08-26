add_library(PDRProcessGraph SHARED
    src/ProcessDependencyGraph.cpp
    src/ProcessLifecycleImpact.cpp)
add_library(PocoDDS::ProcessGraph ALIAS PDRProcessGraph)
set_target_properties(PDRProcessGraph PROPERTIES EXPORT_NAME ProcessGraph)
target_include_directories(PDRProcessGraph
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_definitions(PDRProcessGraph PRIVATE PDR_PROCESS_GRAPH_EXPORTS)
target_link_libraries(PDRProcessGraph PRIVATE Poco::Foundation)
pdr_isolate_embedded_static_dependencies(PDRProcessGraph)
pdr_set_warnings(PDRProcessGraph)

add_library(PDRProcessManagement SHARED
    src/ProcessDesiredStateStore.cpp
    src/SubprocessManager.cpp)
add_library(PocoDDS::ProcessManagement ALIAS PDRProcessManagement)

target_include_directories(PDRProcessManagement
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_definitions(PDRProcessManagement
    PRIVATE PDR_PROCESS_MANAGEMENT_EXPORTS)
target_link_libraries(PDRProcessManagement
    PRIVATE
        PDRProcessGraph
        Poco::JSON
        Poco::Util
        Poco::Foundation)
pdr_isolate_embedded_static_dependencies(PDRProcessManagement)
pdr_set_warnings(PDRProcessManagement)

if(BUILD_TESTING)
    add_executable(pdr-subprocess-manager-supervision-smoke
        tests/SubprocessManagerSupervisionSmoke.cpp)
    target_link_libraries(pdr-subprocess-manager-supervision-smoke PRIVATE
        PocoDDS::ProcessManagement
        Poco::Foundation)
    pdr_set_warnings(pdr-subprocess-manager-supervision-smoke)
    add_test(NAME subprocess-manager-supervision-smoke
        COMMAND pdr-subprocess-manager-supervision-smoke)
    set_tests_properties(subprocess-manager-supervision-smoke PROPERTIES
        LABELS "runtime;process-management;subprocess;supervision;recovery;fault-injection;release"
        TIMEOUT 20)
    if(WIN32)
        set_tests_properties(subprocess-manager-supervision-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
    endif()

    add_executable(pdr-subprocess-manager-dependency-smoke
        tests/SubprocessManagerDependencySmoke.cpp)
    target_link_libraries(pdr-subprocess-manager-dependency-smoke PRIVATE
        PocoDDS::ProcessManagement
        PocoDDS::ProcessGraph
        Poco::Util
        Poco::Foundation)
    pdr_set_warnings(pdr-subprocess-manager-dependency-smoke)
    add_test(NAME subprocess-manager-dependency-smoke
        COMMAND pdr-subprocess-manager-dependency-smoke)
    set_tests_properties(subprocess-manager-dependency-smoke PROPERTIES
        LABELS "runtime;process-management;subprocess;dependency;recovery;fault-injection;release"
        TIMEOUT 20)
    if(WIN32)
        set_tests_properties(subprocess-manager-dependency-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
    endif()

    add_executable(pdr-subprocess-manager-desired-state-smoke
        tests/SubprocessManagerDesiredStateSmoke.cpp)
    target_link_libraries(pdr-subprocess-manager-desired-state-smoke PRIVATE
        PocoDDS::ProcessManagement
        PocoDDS::ProcessGraph
        Poco::Util
        Poco::Foundation)
    pdr_set_warnings(pdr-subprocess-manager-desired-state-smoke)
    add_test(NAME subprocess-manager-desired-state-smoke
        COMMAND pdr-subprocess-manager-desired-state-smoke)
    set_tests_properties(subprocess-manager-desired-state-smoke PROPERTIES
        LABELS "runtime;process-management;subprocess;persistence;recovery;fault-injection;release"
        TIMEOUT 30)
    if(WIN32)
        set_tests_properties(subprocess-manager-desired-state-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
    endif()

    add_executable(pdr-process-desired-state-store-durability-smoke
        src/ProcessDesiredStateStore.cpp
        tests/ProcessDesiredStateStoreDurabilitySmoke.cpp)
    target_include_directories(
        pdr-process-desired-state-store-durability-smoke PRIVATE src)
    target_link_libraries(
        pdr-process-desired-state-store-durability-smoke PRIVATE
        Poco::JSON
        Poco::Foundation)
    pdr_set_warnings(pdr-process-desired-state-store-durability-smoke)
    add_test(NAME process-desired-state-store-durability-smoke
        COMMAND pdr-process-desired-state-store-durability-smoke)
    set_tests_properties(
        process-desired-state-store-durability-smoke PROPERTIES
        LABELS "runtime;process-management;persistence;recovery;fault-injection;release"
        TIMEOUT 20)
    if(WIN32)
        set_tests_properties(
            process-desired-state-store-durability-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
    endif()

    add_executable(pdr-process-lifecycle-impact-smoke
        tests/ProcessLifecycleImpactSmoke.cpp)
    target_link_libraries(pdr-process-lifecycle-impact-smoke PRIVATE
        PocoDDS::ProcessGraph)
    pdr_set_warnings(pdr-process-lifecycle-impact-smoke)
    add_test(NAME process-lifecycle-impact-smoke
        COMMAND pdr-process-lifecycle-impact-smoke)
    set_tests_properties(process-lifecycle-impact-smoke PROPERTIES
        LABELS "runtime;process-management;dependency;contract;release"
        TIMEOUT 10)
    if(WIN32)
        set_tests_properties(process-lifecycle-impact-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
    endif()
endif()

install(TARGETS PDRProcessGraph
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(TARGETS PDRProcessManagement
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
