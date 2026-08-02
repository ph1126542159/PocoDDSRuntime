add_library(PDRDeviceModbus src/ModbusRegisterDevice.cpp)
add_library(PocoDDS::ModbusDevice ALIAS PDRDeviceModbus)

target_include_directories(PDRDeviceModbus
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRDeviceModbus
    PUBLIC PocoDDS::DeviceCore PocoDDS::Modbus Poco::Foundation)
pdr_set_warnings(PDRDeviceModbus)

if(BUILD_TESTING)
    add_executable(pdr-modbus-device-smoke tests/ModbusDeviceSmoke.cpp)
    target_link_libraries(pdr-modbus-device-smoke
        PRIVATE PocoDDS::ModbusDevice Poco::Net)
    pdr_set_warnings(pdr-modbus-device-smoke)
    add_test(NAME modbus-device-smoke COMMAND pdr-modbus-device-smoke)
    add_executable(pdr-modbus-device-recovery tests/ModbusRecoveryTest.cpp)
    target_link_libraries(pdr-modbus-device-recovery
        PRIVATE PocoDDS::ModbusDevice Poco::Net)
    pdr_set_warnings(pdr-modbus-device-recovery)
    add_test(NAME modbus-device-recovery COMMAND pdr-modbus-device-recovery)
    set_tests_properties(modbus-device-recovery PROPERTIES
        LABELS "device;fault-injection;protocol;release"
        TIMEOUT 10)
endif()

install(TARGETS PDRDeviceModbus ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
