add_library(PDRDeviceCAN src/CanSignalSensor.cpp)
add_library(PocoDDS::CANDevice ALIAS PDRDeviceCAN)

target_include_directories(PDRDeviceCAN
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRDeviceCAN
    PUBLIC PocoDDS::DeviceCore PocoDDS::CAN Poco::Foundation)
pdr_set_warnings(PDRDeviceCAN)

if(BUILD_TESTING)
    add_executable(pdr-can-signal-sensor-smoke tests/CanSignalSensorSmoke.cpp)
    target_link_libraries(pdr-can-signal-sensor-smoke PRIVATE PocoDDS::CANDevice)
    pdr_set_warnings(pdr-can-signal-sensor-smoke)
    add_test(NAME can-signal-sensor-smoke COMMAND pdr-can-signal-sensor-smoke)
endif()

install(TARGETS PDRDeviceCAN ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
