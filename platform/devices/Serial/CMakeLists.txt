add_library(PDRDeviceSerial src/SerialPortDevice.cpp)
add_library(PocoDDS::SerialDevice ALIAS PDRDeviceSerial)

target_include_directories(PDRDeviceSerial
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRDeviceSerial
    PUBLIC PocoDDS::DeviceCore PocoDDS::SerialProtocol Poco::Foundation)
pdr_set_warnings(PDRDeviceSerial)

if(BUILD_TESTING)
    add_executable(pdr-serial-device-recovery tests/SerialRecoveryTest.cpp)
    target_link_libraries(pdr-serial-device-recovery
        PRIVATE PocoDDS::SerialDevice Poco::Foundation)
    pdr_set_warnings(pdr-serial-device-recovery)
    add_test(NAME serial-device-recovery COMMAND pdr-serial-device-recovery)
    set_tests_properties(serial-device-recovery PROPERTIES
        LABELS "device;fault-injection;protocol;release"
        TIMEOUT 10)
endif()

install(TARGETS PDRDeviceSerial ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
