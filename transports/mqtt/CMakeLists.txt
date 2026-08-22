add_library(PDRMqttTransport STATIC
    src/MqttTransport.cpp
    src/Registration.cpp)
add_library(PocoDDS::MQTTTransport ALIAS PDRMqttTransport)
set_target_properties(PDRMqttTransport PROPERTIES EXPORT_NAME MQTTTransport)
target_include_directories(PDRMqttTransport
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_features(PDRMqttTransport PUBLIC cxx_std_17)
target_compile_definitions(PDRMqttTransport PUBLIC PDR_MQTT_TRANSPORT_STATIC)
target_link_libraries(PDRMqttTransport
    PUBLIC PocoDDS::RuntimeCore
    PRIVATE PocoDDS::MQTT)
pdr_set_warnings(PDRMqttTransport)

install(TARGETS PDRMqttTransport EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
install(FILES README.md
    DESTINATION "${CMAKE_INSTALL_DOCDIR}/transports/mqtt")

if(BUILD_TESTING)
    add_executable(pdr-mqtt-transport-smoke tests/MqttTransportSmoke.cpp)
    target_link_libraries(pdr-mqtt-transport-smoke
        PRIVATE PocoDDS::MQTTTransport PocoDDS::RuntimeCoreTesting Poco::Net)
    pdr_set_warnings(pdr-mqtt-transport-smoke)
    add_test(NAME mqtt-transport-smoke COMMAND pdr-mqtt-transport-smoke)
    set_tests_properties(mqtt-transport-smoke PROPERTIES
        LABELS "transport;mqtt;integration;fault-injection" TIMEOUT 15)
endif()
