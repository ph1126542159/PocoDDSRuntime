add_library(PDRGatewayAPI INTERFACE)
add_library(PocoDDS::GatewayAPI ALIAS PDRGatewayAPI)
set_target_properties(PDRGatewayAPI PROPERTIES EXPORT_NAME GatewayAPI)
target_include_directories(PDRGatewayAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRGatewayAPI INTERFACE
    PocoDDS::Configuration
    PocoDDS::DeviceCore
    PocoDDS::ProtocolCore
    Poco::OSP
    Poco::Util
    Poco::Foundation)

# External OSP plugins can opt into the factory API without reaching into a
# Gateway implementation target. The dependency stays management-plane only.
target_link_libraries(PDRPlugins INTERFACE PocoDDS::GatewayAPI)

install(TARGETS PDRGatewayAPI EXPORT PocoDDSRuntimeTargets)
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")

if(BUILD_TESTING)
    add_executable(pdr-gateway-factory-registry-smoke
        tests/GatewayFactoryRegistrySmoke.cpp)
    target_link_libraries(pdr-gateway-factory-registry-smoke PRIVATE
        PocoDDS::GatewayAPI)
    pdr_set_warnings(pdr-gateway-factory-registry-smoke)
    add_test(NAME gateway-factory-registry-smoke
        COMMAND pdr-gateway-factory-registry-smoke)
    set_tests_properties(gateway-factory-registry-smoke PROPERTIES
        LABELS "gateway;plugin;contract")
endif()
