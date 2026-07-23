add_library(PDRProtocolMQTT
    src/MqttClient.cpp)
add_library(PocoDDS::MQTT ALIAS PDRProtocolMQTT)

target_include_directories(PDRProtocolMQTT
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)

target_compile_definitions(PDRProtocolMQTT PRIVATE PAHO_MQTT_STATIC)
target_link_libraries(PDRProtocolMQTT
    PUBLIC
        eclipse-paho-mqtt-c::paho-mqtt3c-static
        Poco::Foundation)
pdr_set_warnings(PDRProtocolMQTT)

if(BUILD_TESTING)
    add_executable(pdr-mqtt-smoke tests/MqttSmoke.cpp)
    target_link_libraries(pdr-mqtt-smoke PRIVATE PocoDDS::MQTT Poco::Net)
    pdr_set_warnings(pdr-mqtt-smoke)
    add_test(NAME mqtt-smoke COMMAND pdr-mqtt-smoke)
endif()

install(TARGETS PDRProtocolMQTT ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
