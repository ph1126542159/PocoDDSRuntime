add_library(PDRReliability INTERFACE)
add_library(PocoDDS::Reliability ALIAS PDRReliability)
target_include_directories(PDRReliability INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)

if(BUILD_TESTING)
    add_executable(pdr-reliability-smoke tests/ReliabilitySmoke.cpp)
    target_link_libraries(pdr-reliability-smoke PRIVATE PocoDDS::Reliability)
    pdr_set_warnings(pdr-reliability-smoke)
    add_test(NAME reliability-smoke COMMAND pdr-reliability-smoke)
endif()

install(TARGETS PDRReliability EXPORT PocoDDSRuntimeTargets)
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
