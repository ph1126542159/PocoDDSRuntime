add_library(PDRProtocols INTERFACE)
add_library(PocoDDS::Protocols ALIAS PDRProtocols)

add_subdirectory(BtLE)
add_subdirectory(CAN)
add_subdirectory(Modbus)
add_subdirectory(MQTT)
add_subdirectory(ROS)
add_subdirectory(Serial)
add_subdirectory(UDP)
add_subdirectory(WebTunnel)
add_subdirectory(XBee)

target_include_directories(PDRProtocols
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRProtocols
    INTERFACE
        PocoDDS::BtLE
        PocoDDS::CAN
        PocoDDS::Modbus
        PocoDDS::MQTT
        PocoDDS::ROS
        PocoDDS::SerialProtocol
        PocoDDS::UDP
        PocoDDS::WebTunnelProtocol
        PocoDDS::XBee)

if(BUILD_TESTING)
    add_executable(pdr-protocol-smoke tests/ProtocolSmoke.cpp)
    target_link_libraries(pdr-protocol-smoke PRIVATE PocoDDS::Protocols)
    pdr_set_warnings(pdr-protocol-smoke)
    add_test(NAME protocol-smoke COMMAND pdr-protocol-smoke)
endif()

install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
