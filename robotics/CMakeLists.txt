add_library(PDRRoboticsRuntime
    src/Action.cpp
    src/Behavior.cpp
    src/Business.cpp
    src/BusinessPlugin.cpp
    src/ExternalHardware.cpp
    src/ExternalSimulator.cpp
    src/InMemorySimulator.cpp
    src/Lifecycle.cpp
    src/MockHardware.cpp
    src/ReferenceBusinessModules.cpp
    src/RobotRuntime.cpp
    src/SafetyBoundary.cpp)
add_library(PocoDDS::RoboticsRuntime ALIAS PDRRoboticsRuntime)
set_target_properties(PDRRoboticsRuntime PROPERTIES EXPORT_NAME RoboticsRuntime)

target_include_directories(PDRRoboticsRuntime
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_features(PDRRoboticsRuntime PUBLIC cxx_std_17)
target_link_libraries(PDRRoboticsRuntime PRIVATE ${CMAKE_DL_LIBS})
pdr_set_warnings(PDRRoboticsRuntime)

add_executable(pdr-robot-sim apps/RobotSimulation.cpp)
target_link_libraries(pdr-robot-sim PRIVATE PocoDDS::RoboticsRuntime)
pdr_set_warnings(pdr-robot-sim)

add_executable(pdr-business-sim apps/BusinessSimulation.cpp)
target_link_libraries(pdr-business-sim PRIVATE PocoDDS::RoboticsRuntime)
pdr_set_warnings(pdr-business-sim)

install(TARGETS PDRRoboticsRuntime EXPORT PDRRoboticsRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(TARGETS pdr-robot-sim RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(TARGETS pdr-business-sim RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
install(PROGRAMS tools/robotics_web_server.py
    DESTINATION "${CMAKE_INSTALL_DATADIR}/PDRRoboticsRuntime/tools")
install(DIRECTORY webui/
    DESTINATION "${CMAKE_INSTALL_DATADIR}/PDRRoboticsRuntime/webui")
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
    add_library(pdr-sample-business-plugin MODULE examples/SampleBusinessPlugin.cpp)
    target_link_libraries(pdr-sample-business-plugin PRIVATE PocoDDS::RoboticsRuntime)
    pdr_set_warnings(pdr-sample-business-plugin)
    set_target_properties(pdr-sample-business-plugin PROPERTIES PREFIX "")

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
    foreach(module warehouse inspection pick_place)
        add_test(NAME robotics-business-${module}
            COMMAND pdr-business-sim --module ${module} --period-ms 10 --max-steps 5000)
        set_tests_properties(robotics-business-${module} PROPERTIES
            LABELS "robotics;business;simulation;safety;sil"
            PASS_REGULAR_EXPRESSION "PDR_BUSINESS_SIM_PASS module=${module}"
            TIMEOUT 30)
    endforeach()
    add_test(NAME robotics-business-plugin
        COMMAND pdr-business-sim
            --plugin $<TARGET_FILE:pdr-sample-business-plugin>
            --module custom_cleaning --period-ms 10 --max-steps 5000)
    set_tests_properties(robotics-business-plugin PROPERTIES
        LABELS "robotics;business;plugin;simulation;safety;sil"
        PASS_REGULAR_EXPRESSION "PDR_BUSINESS_SIM_PASS module=custom_cleaning"
        TIMEOUT 30)

    find_package(Python3 COMPONENTS Interpreter QUIET)
    if(Python3_Interpreter_FOUND)
        add_test(NAME robotics-business-webui
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/test_robotics_web_server.py"
                --server "${CMAKE_CURRENT_SOURCE_DIR}/tools/robotics_web_server.py"
                --binary "$<TARGET_FILE:pdr-business-sim>"
                --static-dir "${CMAKE_CURRENT_SOURCE_DIR}/webui")
        set_tests_properties(robotics-business-webui PROPERTIES
            LABELS "robotics;business;simulation;webui;sil"
            PASS_REGULAR_EXPRESSION "PDR_ROBOTICS_WEB_TEST_PASS"
            TIMEOUT 60)
    endif()
endif()
