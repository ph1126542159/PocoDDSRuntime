add_library(PDRRoboticsRuntime
    src/Action.cpp
    src/Behavior.cpp
    src/ExternalHardware.cpp
    src/ExternalSimulator.cpp
    src/InMemorySimulator.cpp
    src/Lifecycle.cpp
    src/MockHardware.cpp
    src/RobotRuntime.cpp
    src/SafetyBoundary.cpp)
add_library(PocoDDS::RoboticsRuntime ALIAS PDRRoboticsRuntime)
set_target_properties(PDRRoboticsRuntime PROPERTIES EXPORT_NAME RoboticsRuntime)

target_include_directories(PDRRoboticsRuntime
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_features(PDRRoboticsRuntime PUBLIC cxx_std_17)
pdr_set_warnings(PDRRoboticsRuntime)

install(TARGETS PDRRoboticsRuntime EXPORT PDRRoboticsRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
install(EXPORT PDRRoboticsRuntimeTargets
    FILE PDRRoboticsRuntimeTargets.cmake
    NAMESPACE PocoDDS::
    DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/PDRRoboticsRuntime")
include(CMakePackageConfigHelpers)
configure_package_config_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/PDRRoboticsRuntimeConfig.cmake.in"
    "${CMAKE_CURRENT_BINARY_DIR}/PDRRoboticsRuntimeConfig.cmake"
    INSTALL_DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/PDRRoboticsRuntime")
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/PDRRoboticsRuntimeConfigVersion.cmake"
    VERSION "${PROJECT_VERSION}"
    COMPATIBILITY SameMajorVersion)
install(FILES
    "${CMAKE_CURRENT_BINARY_DIR}/PDRRoboticsRuntimeConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/PDRRoboticsRuntimeConfigVersion.cmake"
    DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/PDRRoboticsRuntime")

if(BUILD_TESTING)
    add_executable(pdr-robotics-runtime-test tests/RoboticsRuntimeTest.cpp)
    target_link_libraries(pdr-robotics-runtime-test PRIVATE PocoDDS::RoboticsRuntime)
    pdr_set_warnings(pdr-robotics-runtime-test)
    add_test(NAME robotics-runtime COMMAND pdr-robotics-runtime-test)
    set_tests_properties(robotics-runtime PROPERTIES LABELS "robotics;simulation;safety")
endif()
