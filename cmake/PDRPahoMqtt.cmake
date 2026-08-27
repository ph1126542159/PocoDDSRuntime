include_guard(GLOBAL)

function(pdr_require_paho_mqtt)
    find_package(eclipse-paho-mqtt-c CONFIG QUIET PATHS "${PDR_INSTALL_PREFIX}")
    if(TARGET eclipse-paho-mqtt-c::paho-mqtt3a-static OR
       TARGET paho-mqtt3a-static)
        include("${CMAKE_CURRENT_FUNCTION_LIST_DIR}/PDRPahoMqttPatchPolicy.cmake")
        pdr_paho_mqtt_has_callback_teardown_fix(_paho_callback_teardown_safe)
        if(_paho_callback_teardown_safe)
            return()
        endif()
        message(FATAL_ERROR
            "Eclipse Paho MQTT C is installed but lacks PocoDDSRuntime's "
            "callback-teardown safety contract. Rebuild the dependency "
            "superbuild target paho_mqtt_c before configuring MQTT support.")
    endif()
    message(FATAL_ERROR
        "Eclipse Paho MQTT C was requested but is not installed. Build the "
        "dependency superbuild target paho_mqtt_c first.")
endfunction()
