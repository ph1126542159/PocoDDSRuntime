add_library(PDRProtocolUDP
    src/UdpChannel.cpp)
add_library(PocoDDS::UDP ALIAS PDRProtocolUDP)

target_include_directories(PDRProtocolUDP
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)

target_link_libraries(PDRProtocolUDP PUBLIC PocoDDS::Reliability Poco::Net Poco::Foundation)
pdr_set_warnings(PDRProtocolUDP)
set_target_properties(PDRProtocolUDP PROPERTIES EXPORT_NAME UDP)

if(BUILD_TESTING)
    add_executable(pdr-udp-smoke tests/UdpSmoke.cpp)
    target_link_libraries(pdr-udp-smoke PRIVATE PocoDDS::UDP)
    pdr_set_warnings(pdr-udp-smoke)
    add_test(NAME udp-smoke COMMAND pdr-udp-smoke)
    set_tests_properties(udp-smoke PROPERTIES LABELS "protocol;release")
endif()
install(TARGETS PDRProtocolUDP EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
