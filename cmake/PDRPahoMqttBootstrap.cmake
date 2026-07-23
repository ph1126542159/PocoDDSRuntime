find_package(eclipse-paho-mqtt-c CONFIG QUIET)
if(eclipse-paho-mqtt-c_FOUND)
    message(STATUS "Using existing Eclipse Paho MQTT C")
    return()
endif()

set(PDR_PAHO_MQTT_SOURCE_DIR "" CACHE PATH
    "Optional pre-populated Eclipse Paho MQTT C source directory")
set(_paho_source_args
    GIT_REPOSITORY https://github.com/eclipse-paho/paho.mqtt.c.git
    GIT_TAG v1.3.15
    GIT_SHALLOW TRUE)
if(PDR_PAHO_MQTT_SOURCE_DIR)
    set(_paho_source_args
        SOURCE_DIR "${PDR_PAHO_MQTT_SOURCE_DIR}"
        DOWNLOAD_COMMAND "")
endif()

ExternalProject_Add(paho_mqtt_c
    ${_paho_source_args}
    CMAKE_ARGS
        ${PDR_DEPENDENCY_CMAKE_ARGS}
        -DPAHO_BUILD_STATIC=ON
        -DPAHO_BUILD_SHARED=OFF
        -DPAHO_BUILD_SAMPLES=OFF
        -DPAHO_ENABLE_TESTING=OFF
        -DPAHO_WITH_SSL=OFF
        -DPAHO_HIGH_PERFORMANCE=ON)

unset(_paho_source_args)
