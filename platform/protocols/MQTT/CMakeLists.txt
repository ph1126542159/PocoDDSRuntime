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
        PocoDDS::Reliability
        eclipse-paho-mqtt-c::paho-mqtt3cs-static
        Poco::Foundation)
pdr_set_warnings(PDRProtocolMQTT)
set_target_properties(PDRProtocolMQTT PROPERTIES EXPORT_NAME MQTT)

if(BUILD_TESTING)
    find_package(Python3 3.9 QUIET COMPONENTS Interpreter)
    add_executable(pdr-mqtt-smoke tests/MqttSmoke.cpp)
    target_link_libraries(pdr-mqtt-smoke PRIVATE PocoDDS::MQTT Poco::Net)
    pdr_set_warnings(pdr-mqtt-smoke)
    add_test(NAME mqtt-smoke COMMAND pdr-mqtt-smoke)

    add_executable(pdr-mqtt-tls-probe tests/MqttTlsProbe.cpp)
    target_link_libraries(pdr-mqtt-tls-probe PRIVATE PocoDDS::MQTT)
    pdr_set_warnings(pdr-mqtt-tls-probe)
    find_program(PDR_OPENSSL_EXECUTABLE openssl
        HINTS "${OPENSSL_ROOT_DIR}/bin"
              "${OPENSSL_INCLUDE_DIR}/../bin")
    # The end-to-end probe asserts the SystemMonitoring /api/v1/protocols view.
    # Keep the standalone MQTT/TLS probe available in lean profiles, but only
    # register this management-plane integration when that API is packaged.
    if(PDR_ENABLE_OBSERVABILITY AND PDR_OPENSSL_EXECUTABLE AND Python3_EXECUTABLE)
        add_test(NAME mqtt-tls-integration
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_SOURCE_DIR}/tools/mqtt_tls_integration.py"
                --openssl "${PDR_OPENSSL_EXECUTABLE}"
                --probe "$<TARGET_FILE:pdr-mqtt-tls-probe>"
                --runtime-smoke "${CMAKE_SOURCE_DIR}/tools/runtime_smoke.py"
                --runtime "$<TARGET_FILE:pdr-runtime>"
                --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                --config "${CMAKE_SOURCE_DIR}/config/pdr-runtime.properties"
                --install-bin "${PDR_INSTALL_PREFIX}/bin"
                --report "${CMAKE_BINARY_DIR}/reports/runtime-mqtt-tls-integration.json")
        set_tests_properties(mqtt-tls-integration PROPERTIES
            LABELS "protocol;integration;security;runtime" TIMEOUT 45
            RESOURCE_LOCK pdr_runtime_http)
    endif()
endif()

install(TARGETS PDRProtocolMQTT EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
