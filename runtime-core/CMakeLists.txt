add_library(PDRRuntimeCore
    src/Transport.cpp
    src/Codec.cpp
    src/Executor.cpp
    src/InProcessTransport.cpp
    src/StaticHost.cpp
    src/TransportRegistry.cpp)
add_library(PocoDDS::RuntimeCore ALIAS PDRRuntimeCore)
set_target_properties(PDRRuntimeCore PROPERTIES EXPORT_NAME RuntimeCore)
target_include_directories(PDRRuntimeCore
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_features(PDRRuntimeCore PUBLIC cxx_std_17)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRRuntimeCore PUBLIC PDR_RUNTIME_CORE_STATIC)
endif()
pdr_set_warnings(PDRRuntimeCore)

add_library(PDRRuntimeCoreTesting STATIC testing/src/TransportConformance.cpp)
add_library(PocoDDS::RuntimeCoreTesting ALIAS PDRRuntimeCoreTesting)
set_target_properties(PDRRuntimeCoreTesting PROPERTIES EXPORT_NAME RuntimeCoreTesting)
target_include_directories(PDRRuntimeCoreTesting
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/testing/include>
        $<INSTALL_INTERFACE:include>)
target_compile_features(PDRRuntimeCoreTesting PUBLIC cxx_std_17)
target_compile_definitions(PDRRuntimeCoreTesting PUBLIC PDR_RUNTIME_CORE_TESTING_STATIC)
target_link_libraries(PDRRuntimeCoreTesting PUBLIC PocoDDS::RuntimeCore)
pdr_set_warnings(PDRRuntimeCoreTesting)

install(TARGETS PDRRuntimeCore PDRRuntimeCoreTesting EXPORT PDRRuntimeCoreTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
install(DIRECTORY testing/include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
install(FILES README.md DESTINATION "${CMAKE_INSTALL_DATADIR}/doc/PocoDDSRuntime"
    RENAME runtime-core.md)

include(CMakePackageConfigHelpers)
set(PDR_RUNTIME_CORE_CMAKE_DIR "${CMAKE_INSTALL_LIBDIR}/cmake/PDRRuntimeCore")
configure_package_config_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/PDRRuntimeCoreConfig.cmake.in"
    "${CMAKE_CURRENT_BINARY_DIR}/PDRRuntimeCoreConfig.cmake"
    INSTALL_DESTINATION "${PDR_RUNTIME_CORE_CMAKE_DIR}")
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/PDRRuntimeCoreConfigVersion.cmake"
    VERSION "${PROJECT_VERSION}"
    COMPATIBILITY SameMajorVersion)
install(EXPORT PDRRuntimeCoreTargets
    FILE PDRRuntimeCoreTargets.cmake
    NAMESPACE PocoDDS::
    DESTINATION "${PDR_RUNTIME_CORE_CMAKE_DIR}")
install(FILES
    "${CMAKE_CURRENT_BINARY_DIR}/PDRRuntimeCoreConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/PDRRuntimeCoreConfigVersion.cmake"
    DESTINATION "${PDR_RUNTIME_CORE_CMAKE_DIR}")

if(BUILD_TESTING)
    set(PDR_RUNTIME_CORE_INPROC_AVERAGE_BUDGET_US 50 CACHE STRING
        "Maximum average RuntimeCore in-process publish latency in microseconds")
    set(PDR_RUNTIME_CORE_INPROC_P99_BUDGET_US 200 CACHE STRING
        "Maximum p99 RuntimeCore in-process publish latency in microseconds")

    add_executable(pdr-runtime-core-inproc-performance
        benchmarks/InProcessTransportPerformance.cpp)
    target_link_libraries(pdr-runtime-core-inproc-performance PRIVATE PocoDDS::RuntimeCore)
    target_compile_definitions(pdr-runtime-core-inproc-performance PRIVATE
        PDR_RUNTIME_CORE_INPROC_AVERAGE_BUDGET_US=${PDR_RUNTIME_CORE_INPROC_AVERAGE_BUDGET_US}
        PDR_RUNTIME_CORE_INPROC_P99_BUDGET_US=${PDR_RUNTIME_CORE_INPROC_P99_BUDGET_US})
    pdr_set_warnings(pdr-runtime-core-inproc-performance)
    add_test(NAME runtime-core-inproc-performance-budget
        COMMAND pdr-runtime-core-inproc-performance)
    set_tests_properties(runtime-core-inproc-performance-budget PROPERTIES
        LABELS "core;transport;desktop;performance" TIMEOUT 15)

    add_executable(pdr-runtime-core-codec-smoke tests/CodecSmoke.cpp)
    target_link_libraries(pdr-runtime-core-codec-smoke PRIVATE PocoDDS::RuntimeCore)
    pdr_set_warnings(pdr-runtime-core-codec-smoke)
    add_test(NAME runtime-core-codec-smoke COMMAND pdr-runtime-core-codec-smoke)

    add_executable(pdr-runtime-core-transport-conformance-smoke
        tests/TransportConformanceSmoke.cpp)
    target_link_libraries(pdr-runtime-core-transport-conformance-smoke
        PRIVATE PocoDDS::RuntimeCoreTesting)
    pdr_set_warnings(pdr-runtime-core-transport-conformance-smoke)
    add_test(NAME runtime-core-transport-conformance-smoke
        COMMAND pdr-runtime-core-transport-conformance-smoke)

    add_executable(pdr-runtime-core-executor-smoke tests/ExecutorSmoke.cpp)
    target_link_libraries(pdr-runtime-core-executor-smoke PRIVATE PocoDDS::RuntimeCore)
    pdr_set_warnings(pdr-runtime-core-executor-smoke)
    add_test(NAME runtime-core-executor-smoke COMMAND pdr-runtime-core-executor-smoke)

    add_executable(pdr-runtime-core-inproc-smoke tests/InProcessTransportSmoke.cpp)
    target_link_libraries(pdr-runtime-core-inproc-smoke PRIVATE PocoDDS::RuntimeCore)
    pdr_set_warnings(pdr-runtime-core-inproc-smoke)
    add_test(NAME runtime-core-inproc-smoke COMMAND pdr-runtime-core-inproc-smoke)
    set_tests_properties(runtime-core-inproc-smoke PROPERTIES
        LABELS "core;transport;desktop;performance")

    add_executable(pdr-runtime-core-async-smoke tests/AsyncTransportSmoke.cpp)
    target_link_libraries(pdr-runtime-core-async-smoke PRIVATE PocoDDS::RuntimeCore)
    pdr_set_warnings(pdr-runtime-core-async-smoke)
    add_test(NAME runtime-core-async-smoke COMMAND pdr-runtime-core-async-smoke)

    add_executable(pdr-runtime-core-host-smoke tests/StaticHostSmoke.cpp)
    target_link_libraries(pdr-runtime-core-host-smoke PRIVATE PocoDDS::RuntimeCore)
    pdr_set_warnings(pdr-runtime-core-host-smoke)
    add_test(NAME runtime-core-host-smoke COMMAND pdr-runtime-core-host-smoke)

    add_executable(pdr-runtime-core-transport-registry-smoke
        tests/TransportRegistrySmoke.cpp)
    target_link_libraries(pdr-runtime-core-transport-registry-smoke
        PRIVATE PocoDDS::RuntimeCore)
    pdr_set_warnings(pdr-runtime-core-transport-registry-smoke)
    add_test(NAME runtime-core-transport-registry-smoke
        COMMAND pdr-runtime-core-transport-registry-smoke)

    set_tests_properties(runtime-core-executor-smoke runtime-core-async-smoke
                         runtime-core-host-smoke
                         runtime-core-transport-registry-smoke
                         runtime-core-transport-conformance-smoke
                         runtime-core-codec-smoke PROPERTIES
        LABELS "core;transport;desktop;concurrency")
endif()
