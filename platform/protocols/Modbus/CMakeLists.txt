add_library(PDRProtocolModbus
    src/ModbusTcpClient.cpp
    src/ModbusTcpCodec.cpp)
add_library(PocoDDS::Modbus ALIAS PDRProtocolModbus)

target_include_directories(PDRProtocolModbus
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)

pdr_set_warnings(PDRProtocolModbus)
target_link_libraries(PDRProtocolModbus
    PUBLIC Poco::Net Poco::Foundation)
if(BUILD_TESTING)
    add_executable(pdr-modbus-disconnect-recovery tests/DisconnectRecoveryTest.cpp)
    target_link_libraries(pdr-modbus-disconnect-recovery PRIVATE PocoDDS::Modbus)
    pdr_set_warnings(pdr-modbus-disconnect-recovery)
    add_test(NAME modbus-disconnect-recovery COMMAND pdr-modbus-disconnect-recovery)
    set_tests_properties(modbus-disconnect-recovery PROPERTIES
        LABELS "fault-injection;nightly;protocol"
        TIMEOUT 10)
endif()
install(TARGETS PDRProtocolModbus ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
