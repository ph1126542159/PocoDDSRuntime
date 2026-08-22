add_library(PDRNativeProcess STATIC src/NativeProcessSupervisor.cpp)
add_library(PocoDDS::NativeProcess ALIAS PDRNativeProcess)
set_target_properties(PDRNativeProcess PROPERTIES EXPORT_NAME NativeProcess)
target_include_directories(PDRNativeProcess
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_features(PDRNativeProcess PUBLIC cxx_std_17)
target_compile_definitions(PDRNativeProcess PUBLIC PDR_NATIVE_PROCESS_STATIC)
target_link_libraries(PDRNativeProcess PUBLIC PocoDDS::RuntimeCore)
pdr_set_warnings(PDRNativeProcess)

install(TARGETS PDRNativeProcess EXPORT PDRNativeProcessTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
install(FILES README.md DESTINATION "${CMAKE_INSTALL_DATADIR}/doc/PocoDDSRuntime"
    RENAME native-process.md)

include(CMakePackageConfigHelpers)
set(PDR_NATIVE_PROCESS_CMAKE_DIR "${CMAKE_INSTALL_LIBDIR}/cmake/PDRNativeProcess")
configure_package_config_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/PDRNativeProcessConfig.cmake.in"
    "${CMAKE_CURRENT_BINARY_DIR}/PDRNativeProcessConfig.cmake"
    INSTALL_DESTINATION "${PDR_NATIVE_PROCESS_CMAKE_DIR}")
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/PDRNativeProcessConfigVersion.cmake"
    VERSION "${PROJECT_VERSION}"
    COMPATIBILITY SameMajorVersion)
install(EXPORT PDRNativeProcessTargets
    FILE PDRNativeProcessTargets.cmake
    NAMESPACE PocoDDS::
    DESTINATION "${PDR_NATIVE_PROCESS_CMAKE_DIR}")
install(FILES
    "${CMAKE_CURRENT_BINARY_DIR}/PDRNativeProcessConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/PDRNativeProcessConfigVersion.cmake"
    DESTINATION "${PDR_NATIVE_PROCESS_CMAKE_DIR}")

if(BUILD_TESTING)
    add_executable(pdr-native-process-smoke tests/NativeProcessSupervisorSmoke.cpp)
    target_link_libraries(pdr-native-process-smoke PRIVATE PocoDDS::NativeProcess)
    pdr_set_warnings(pdr-native-process-smoke)
    add_test(NAME native-process-smoke COMMAND pdr-native-process-smoke)
    set_tests_properties(native-process-smoke PROPERTIES
        LABELS "process;desktop;cross-process;fault-injection" TIMEOUT 20)
endif()
