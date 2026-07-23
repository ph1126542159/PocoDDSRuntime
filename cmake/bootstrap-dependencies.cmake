cmake_minimum_required(VERSION 3.24)
include(ExternalProject)
include("${CMAKE_CURRENT_LIST_DIR}/PDRThirdPartyCommon.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/PDRPocoBootstrap.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/PDRFastDDSBootstrap.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/PDRPahoMqttBootstrap.cmake")

option(PDR_BUILD_OPENTELEMETRY
    "Build the OpenTelemetry C++ dependency" ON)
option(PDR_BUILD_GOOGLETEST
    "Build the optional GoogleTest dependency" OFF)

if(PDR_BUILD_OPENTELEMETRY)
    include("${CMAKE_CURRENT_LIST_DIR}/PDROpenTelemetryBootstrap.cmake")
endif()
if(PDR_BUILD_GOOGLETEST)
    include("${CMAKE_CURRENT_LIST_DIR}/PDRGoogleTestBootstrap.cmake")
endif()
