add_library(PDRProtocolWebTunnel src/LocalForwarder.cpp)
add_library(PocoDDS::WebTunnelProtocol ALIAS PDRProtocolWebTunnel)

target_include_directories(PDRProtocolWebTunnel
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRProtocolWebTunnel
    PUBLIC Poco::Foundation WebTunnel
    PRIVATE Poco::Net Poco::NetSSL)
pdr_set_warnings(PDRProtocolWebTunnel)
set_target_properties(PDRProtocolWebTunnel PROPERTIES EXPORT_NAME WebTunnelProtocol)

if(BUILD_TESTING)
    find_package(Python3 3.9 QUIET COMPONENTS Interpreter)
    add_executable(pdr-webtunnel-protocol-smoke tests/WebTunnelSmoke.cpp)
    target_link_libraries(pdr-webtunnel-protocol-smoke PRIVATE PocoDDS::WebTunnelProtocol)
    pdr_set_warnings(pdr-webtunnel-protocol-smoke)
    add_test(NAME webtunnel-protocol-smoke COMMAND pdr-webtunnel-protocol-smoke)

    add_executable(pdr-webtunnel-local-forwarder-integration
        tests/LocalForwarderIntegration.cpp)
    target_link_libraries(pdr-webtunnel-local-forwarder-integration
        PRIVATE PocoDDS::WebTunnelProtocol Poco::Net)
    pdr_set_warnings(pdr-webtunnel-local-forwarder-integration)
    set_target_properties(pdr-webtunnel-local-forwarder-integration
        PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${PDR_TEST_RUNTIME_DIR}")
    add_test(NAME webtunnel-local-forwarder-integration
        COMMAND pdr-webtunnel-local-forwarder-integration)
    set_tests_properties(webtunnel-local-forwarder-integration PROPERTIES
        LABELS "protocol;integration"
        TIMEOUT 20)

    add_executable(pdr-webtunnel-tls-probe tests/LocalForwarderTlsProbe.cpp)
    target_link_libraries(pdr-webtunnel-tls-probe
        PRIVATE PocoDDS::WebTunnelProtocol Poco::Net)
    pdr_set_warnings(pdr-webtunnel-tls-probe)
    set_target_properties(pdr-webtunnel-tls-probe
        PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${PDR_TEST_RUNTIME_DIR}")
    if(PDR_OPENSSL_EXECUTABLE AND Python3_EXECUTABLE)
        add_test(NAME webtunnel-tls-integration
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_SOURCE_DIR}/tools/webtunnel_tls_integration.py"
                --openssl "${PDR_OPENSSL_EXECUTABLE}"
                --probe "$<TARGET_FILE:pdr-webtunnel-tls-probe>")
        set_tests_properties(webtunnel-tls-integration PROPERTIES
            LABELS "protocol;integration;security"
            TIMEOUT 45)
    endif()
endif()

install(TARGETS PDRProtocolWebTunnel EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
