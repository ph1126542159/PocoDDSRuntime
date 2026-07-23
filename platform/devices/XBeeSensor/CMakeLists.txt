add_library(PDRDeviceXBeeSensor src/XBeeAnalogSensor.cpp)
add_library(PocoDDS::XBeeSensor ALIAS PDRDeviceXBeeSensor)

target_include_directories(PDRDeviceXBeeSensor
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRDeviceXBeeSensor
    PUBLIC PocoDDS::DeviceCore PocoDDS::XBee Poco::Foundation)
pdr_set_warnings(PDRDeviceXBeeSensor)

if(BUILD_TESTING)
    add_executable(pdr-xbee-sensor-smoke tests/XBeeSensorSmoke.cpp)
    target_link_libraries(pdr-xbee-sensor-smoke PRIVATE PocoDDS::XBeeSensor)
    pdr_set_warnings(pdr-xbee-sensor-smoke)
    add_test(NAME xbee-sensor-smoke COMMAND pdr-xbee-sensor-smoke)
endif()

install(TARGETS PDRDeviceXBeeSensor ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
