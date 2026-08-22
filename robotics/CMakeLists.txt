set(PDR_ROBOTICS_PLUGIN_ABI_VERSION 2)
string(REGEX MATCH "^[0-9]+" PDR_ROBOTICS_COMPILER_MAJOR "${CMAKE_CXX_COMPILER_VERSION}")
set(PDR_ROBOTICS_ABI_FINGERPRINT
    "${CMAKE_CXX_COMPILER_ID}-${PDR_ROBOTICS_COMPILER_MAJOR}-${CMAKE_SYSTEM_NAME}-${CMAKE_SYSTEM_PROCESSOR}")
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/include/PocoDDS/Robotics/Version.h.in"
    "${CMAKE_CURRENT_BINARY_DIR}/include/PocoDDS/Robotics/Version.h"
    @ONLY)

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

if(NOT TARGET PocoDDS::RuntimeCore)
    message(FATAL_ERROR
        "PDRRoboticsRuntime requires the transport-neutral PDRRuntimeCore target")
endif()

target_include_directories(PDRRoboticsRuntime
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_features(PDRRoboticsRuntime PUBLIC cxx_std_17)
target_link_libraries(PDRRoboticsRuntime
    PUBLIC PocoDDS::RuntimeCore
    PRIVATE ${CMAKE_DL_LIBS})
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
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
    PATTERN "*.in" EXCLUDE)
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/include/PocoDDS/Robotics/Version.h"
    DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}/PocoDDS/Robotics")
install(PROGRAMS tools/robotics_web_server.py
    DESTINATION "${CMAKE_INSTALL_DATADIR}/PDRRoboticsRuntime/tools")
install(PROGRAMS
    "${CMAKE_SOURCE_DIR}/tools/pdr.py"
    "${CMAKE_SOURCE_DIR}/tools/project_manager.py"
    "${CMAKE_SOURCE_DIR}/tools/project_config.py"
    "${CMAKE_SOURCE_DIR}/tools/project_config_transaction.py"
    "${CMAKE_SOURCE_DIR}/tools/project_template.py"
    "${CMAKE_SOURCE_DIR}/tools/component_template.py"
    "${CMAKE_SOURCE_DIR}/tools/project_pipeline.py"
    "${CMAKE_SOURCE_DIR}/tools/project_package.py"
    "${CMAKE_SOURCE_DIR}/tools/check_architecture.py"
    "${CMAKE_SOURCE_DIR}/tools/release_manifest.py"
    "${CMAKE_SOURCE_DIR}/tools/release_qualification.py"
    "${CMAKE_SOURCE_DIR}/tools/external_acceptance.py"
    "${CMAKE_SOURCE_DIR}/tools/evidence_bundle.py"
    "${CMAKE_SOURCE_DIR}/tools/release_pipeline.py"
    "${CMAKE_SOURCE_DIR}/tools/upgrade_manager.py"
    "${CMAKE_SOURCE_DIR}/tools/plugin_manager.py"
    "${CMAKE_SOURCE_DIR}/tools/upgrade_transaction_integration.py"
    "${CMAKE_SOURCE_DIR}/tools/runtime_smoke.py"
    "${CMAKE_SOURCE_DIR}/tools/soak_runner.py"
    "${CMAKE_SOURCE_DIR}/tools/device_acceptance.py"
    "${CMAKE_SOURCE_DIR}/tools/protocol_acceptance.py"
    "${CMAKE_SOURCE_DIR}/tools/security_gate.py"
    DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(FILES "${CMAKE_SOURCE_DIR}/tools/pdr.ps1"
    DESTINATION "${CMAKE_INSTALL_BINDIR}")
if(NOT WIN32)
    install(PROGRAMS "${CMAKE_SOURCE_DIR}/tools/pdr.py"
        DESTINATION "${CMAKE_INSTALL_BINDIR}" RENAME pdr)
endif()
install(DIRECTORY webui/
    DESTINATION "${CMAKE_INSTALL_DATADIR}/PDRRoboticsRuntime/webui")
install(DIRECTORY "${CMAKE_SOURCE_DIR}/contracts/"
    DESTINATION "${CMAKE_INSTALL_DATADIR}/PDRRoboticsRuntime/contracts")
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
    set(PDR_ROBOTICS_STEP_AVERAGE_BUDGET_US "500.0" CACHE STRING
        "Maximum average RobotRuntime step latency in microseconds")
    set(PDR_ROBOTICS_STEP_P99_BUDGET_US "2000.0" CACHE STRING
        "Maximum p99 RobotRuntime step latency in microseconds")
    add_executable(pdr-robotics-performance benchmarks/RoboticsPerformance.cpp)
    target_link_libraries(pdr-robotics-performance PRIVATE PocoDDS::RoboticsRuntime)
    target_compile_definitions(pdr-robotics-performance PRIVATE
        PDR_ROBOTICS_STEP_AVERAGE_BUDGET_US=${PDR_ROBOTICS_STEP_AVERAGE_BUDGET_US}
        PDR_ROBOTICS_STEP_P99_BUDGET_US=${PDR_ROBOTICS_STEP_P99_BUDGET_US})
    pdr_set_warnings(pdr-robotics-performance)

    find_package(Python3 COMPONENTS Interpreter QUIET)
    if(Python3_Interpreter_FOUND)
        add_test(NAME robotics-architecture-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_SOURCE_DIR}/tools/check_architecture.py"
                --root "${CMAKE_SOURCE_DIR}")
        set_tests_properties(robotics-architecture-policy PROPERTIES
            LABELS "robotics;architecture;policy")
    endif()

    add_test(NAME robotics-performance-budget COMMAND pdr-robotics-performance)
    set_tests_properties(robotics-performance-budget PROPERTIES
        LABELS "robotics;performance;regression"
        PASS_REGULAR_EXPRESSION "PDR_ROBOTICS_PERFORMANCE_PASS"
        TIMEOUT 30)

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

    if(Python3_Interpreter_FOUND)
        add_test(NAME robotics-business-webui
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/test_robotics_web_server.py"
                --server "${CMAKE_CURRENT_SOURCE_DIR}/tools/robotics_web_server.py"
                --binary "$<TARGET_FILE:pdr-business-sim>"
                --static-dir "${CMAKE_CURRENT_SOURCE_DIR}/webui"
                --framework-manifest "${PDR_FRAMEWORK_MODEL_MANIFEST}")
        set_tests_properties(robotics-business-webui PROPERTIES
            LABELS "robotics;business;simulation;webui;sil"
            PASS_REGULAR_EXPRESSION "PDR_ROBOTICS_WEB_TEST_PASS"
            TIMEOUT 60)
    endif()
endif()
