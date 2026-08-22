add_library(PDRLocalIpc STATIC
    src/LocalIpcTransport.cpp
    src/Registration.cpp)
add_library(PocoDDS::LocalIpc ALIAS PDRLocalIpc)
set_target_properties(PDRLocalIpc PROPERTIES EXPORT_NAME LocalIpc)
target_include_directories(PDRLocalIpc
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_features(PDRLocalIpc PUBLIC cxx_std_17)
target_compile_definitions(PDRLocalIpc PUBLIC PDR_LOCAL_IPC_STATIC)
target_link_libraries(PDRLocalIpc PUBLIC PocoDDS::RuntimeCore)
pdr_set_warnings(PDRLocalIpc)

install(TARGETS PDRLocalIpc EXPORT PDRLocalIpcTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
install(FILES "${CMAKE_SOURCE_DIR}/docs/architecture/local-ipc.md"
    DESTINATION "${CMAKE_INSTALL_DATADIR}/doc/PocoDDSRuntime")

include(CMakePackageConfigHelpers)
set(PDR_LOCAL_IPC_CMAKE_DIR "${CMAKE_INSTALL_LIBDIR}/cmake/PDRLocalIpc")
configure_package_config_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/PDRLocalIpcConfig.cmake.in"
    "${CMAKE_CURRENT_BINARY_DIR}/PDRLocalIpcConfig.cmake"
    INSTALL_DESTINATION "${PDR_LOCAL_IPC_CMAKE_DIR}")
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/PDRLocalIpcConfigVersion.cmake"
    VERSION "${PROJECT_VERSION}"
    COMPATIBILITY SameMajorVersion)
install(EXPORT PDRLocalIpcTargets
    FILE PDRLocalIpcTargets.cmake
    NAMESPACE PocoDDS::
    DESTINATION "${PDR_LOCAL_IPC_CMAKE_DIR}")
install(FILES
    "${CMAKE_CURRENT_BINARY_DIR}/PDRLocalIpcConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/PDRLocalIpcConfigVersion.cmake"
    DESTINATION "${PDR_LOCAL_IPC_CMAKE_DIR}")

if(BUILD_TESTING)
    add_executable(pdr-local-ipc-smoke tests/LocalIpcSmoke.cpp)
    target_link_libraries(pdr-local-ipc-smoke
        PRIVATE PocoDDS::LocalIpc PocoDDS::RuntimeCoreTesting)
    pdr_set_warnings(pdr-local-ipc-smoke)
    add_test(NAME local-ipc-smoke COMMAND pdr-local-ipc-smoke)
    set_tests_properties(local-ipc-smoke PROPERTIES
        LABELS "ipc;transport;desktop;fault-injection")

    add_executable(pdr-local-ipc-cross-process tests/LocalIpcCrossProcess.cpp)
    target_link_libraries(pdr-local-ipc-cross-process PRIVATE PocoDDS::LocalIpc)
    pdr_set_warnings(pdr-local-ipc-cross-process)
    add_test(NAME local-ipc-cross-process COMMAND pdr-local-ipc-cross-process)
    set_tests_properties(local-ipc-cross-process PROPERTIES
        LABELS "ipc;transport;desktop;cross-process;fault-injection"
        TIMEOUT 15)
endif()
