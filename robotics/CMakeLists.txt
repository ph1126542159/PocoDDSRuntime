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

add_executable(pdr-robot-sim apps/RobotSimulation.cpp)
target_link_libraries(pdr-robot-sim PRIVATE PocoDDS::RoboticsRuntime)
pdr_set_warnings(pdr-robot-sim)

install(TARGETS PDRRoboticsRuntime EXPORT PDRRoboticsRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(TARGETS pdr-robot-sim RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
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
    add_test(NAME robotics-local-simulation COMMAND pdr-robot-sim --steps 200 --period-ms 5)
    set_tests_properties(robotics-local-simulation PROPERTIES
        LABELS "robotics;simulation;safety;sil"
        PASS_REGULAR_EXPRESSION "PDR_ROBOT_SIM_PASS"
        TIMEOUT 30)
endif()
