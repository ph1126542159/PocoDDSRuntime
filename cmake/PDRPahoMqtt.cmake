include_guard(GLOBAL)

function(pdr_require_paho_mqtt)
    find_package(eclipse-paho-mqtt-c CONFIG QUIET PATHS "${PDR_INSTALL_PREFIX}")
    if(TARGET eclipse-paho-mqtt-c::paho-mqtt3a-static OR
       TARGET paho-mqtt3a-static)
        return()
    endif()
    message(FATAL_ERROR
        "Eclipse Paho MQTT C was requested but is not installed. Build the "
        "dependency superbuild target paho_mqtt_c first.")
endfunction()
