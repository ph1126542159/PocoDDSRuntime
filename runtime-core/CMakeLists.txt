add_library(PDRRuntimeCore
    src/Transport.cpp
    src/InProcessTransport.cpp)
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

install(TARGETS PDRRuntimeCore EXPORT PDRRuntimeCoreTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")

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
    add_executable(pdr-runtime-core-inproc-smoke tests/InProcessTransportSmoke.cpp)
    target_link_libraries(pdr-runtime-core-inproc-smoke PRIVATE PocoDDS::RuntimeCore)
    pdr_set_warnings(pdr-runtime-core-inproc-smoke)
    add_test(NAME runtime-core-inproc-smoke COMMAND pdr-runtime-core-inproc-smoke)
    set_tests_properties(runtime-core-inproc-smoke PROPERTIES
        LABELS "core;transport;desktop;performance")
endif()
