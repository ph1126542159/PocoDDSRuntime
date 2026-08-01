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
    add_executable(pdr-can-device-recovery tests/CanRecoveryTest.cpp)
    target_link_libraries(pdr-can-device-recovery
        PRIVATE PocoDDS::CANDevice Poco::Foundation)
    pdr_set_warnings(pdr-can-device-recovery)
    add_test(NAME can-device-recovery COMMAND pdr-can-device-recovery)
    set_tests_properties(can-device-recovery PROPERTIES
        LABELS "device;fault-injection;protocol;release"
        TIMEOUT 10)
endif()

install(TARGETS PDRDeviceCAN ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
