add_library(PDRReliability INTERFACE)
add_library(PocoDDS::Reliability ALIAS PDRReliability)
set_target_properties(PDRReliability PROPERTIES EXPORT_NAME Reliability)
target_include_directories(PDRReliability INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)

if(BUILD_TESTING)
    add_executable(pdr-reliability-smoke tests/ReliabilitySmoke.cpp)
    target_link_libraries(pdr-reliability-smoke PRIVATE PocoDDS::Reliability)
    pdr_set_warnings(pdr-reliability-smoke)
    add_test(NAME reliability-smoke COMMAND pdr-reliability-smoke)
    add_executable(pdr-reliability-fault-injection tests/FaultInjectionTest.cpp)
    target_link_libraries(pdr-reliability-fault-injection PRIVATE PocoDDS::Reliability)
    pdr_set_warnings(pdr-reliability-fault-injection)
    add_test(NAME reliability-fault-injection COMMAND pdr-reliability-fault-injection)
    set_tests_properties(reliability-fault-injection PROPERTIES LABELS "fault-injection;nightly")
endif()

install(TARGETS PDRReliability EXPORT PocoDDSRuntimeTargets)
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
