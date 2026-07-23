add_library(PDRProtocolWebTunnel INTERFACE)
add_library(PocoDDS::WebTunnelProtocol ALIAS PDRProtocolWebTunnel)

target_include_directories(PDRProtocolWebTunnel
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRProtocolWebTunnel INTERFACE Poco::Foundation WebTunnel)

if(BUILD_TESTING)
    add_executable(pdr-webtunnel-protocol-smoke tests/WebTunnelSmoke.cpp)
    target_link_libraries(pdr-webtunnel-protocol-smoke PRIVATE PocoDDS::WebTunnelProtocol)
    pdr_set_warnings(pdr-webtunnel-protocol-smoke)
    add_test(NAME webtunnel-protocol-smoke COMMAND pdr-webtunnel-protocol-smoke)
endif()

install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
