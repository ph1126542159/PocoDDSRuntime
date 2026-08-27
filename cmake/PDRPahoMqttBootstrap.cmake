find_package(eclipse-paho-mqtt-c CONFIG QUIET)
if(TARGET eclipse-paho-mqtt-c::paho-mqtt3cs-static OR TARGET paho-mqtt3cs-static)
    include("${CMAKE_CURRENT_LIST_DIR}/PDRPahoMqttPatchPolicy.cmake")
    pdr_paho_mqtt_has_callback_teardown_fix(_paho_callback_teardown_safe)
    if(_paho_callback_teardown_safe)
        message(STATUS "Using callback-teardown-safe TLS-enabled Eclipse Paho MQTT C")
        return()
    endif()
    message(STATUS
        "Existing Eclipse Paho MQTT C lacks the callback teardown safety contract; "
        "rebuilding the governed dependency")
endif()

find_package(Git REQUIRED)
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
    PATCH_COMMAND
        "${CMAKE_COMMAND}"
        "-DPDR_PATCH_SOURCE_DIR=<SOURCE_DIR>"
        "-DPDR_PATCH_FILE=${CMAKE_CURRENT_LIST_DIR}/patches/paho-mqtt-c-v1.3.15-message-callback-teardown.patch"
        "-DPDR_GIT_EXECUTABLE=${GIT_EXECUTABLE}"
        -P "${CMAKE_CURRENT_LIST_DIR}/ApplyDependencyPatch.cmake"
    CMAKE_ARGS
        ${PDR_DEPENDENCY_CMAKE_ARGS}
        -DPAHO_BUILD_STATIC=ON
        -DPAHO_BUILD_SHARED=OFF
        -DPAHO_BUILD_SAMPLES=OFF
        -DPAHO_ENABLE_TESTING=OFF
        -DPAHO_WITH_SSL=ON
        -DPAHO_HIGH_PERFORMANCE=ON)

unset(_paho_source_args)
