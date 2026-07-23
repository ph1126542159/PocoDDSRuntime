add_library(PDRDeviceLinux
    src/LinuxSysfsGpioDevice.cpp
    src/LinuxSysfsLedDevice.cpp)
add_library(PocoDDS::LinuxDevices ALIAS PDRDeviceLinux)

target_include_directories(PDRDeviceLinux
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRDeviceLinux PUBLIC PocoDDS::DeviceCore Poco::Foundation)
pdr_set_warnings(PDRDeviceLinux)

if(BUILD_TESTING)
    add_executable(pdr-linux-sysfs-gpio-smoke tests/LinuxSysfsGpioSmoke.cpp)
    target_link_libraries(pdr-linux-sysfs-gpio-smoke PRIVATE PocoDDS::LinuxDevices)
    pdr_set_warnings(pdr-linux-sysfs-gpio-smoke)
    add_test(NAME linux-sysfs-gpio-smoke COMMAND pdr-linux-sysfs-gpio-smoke)

    add_executable(pdr-linux-sysfs-led-smoke tests/LinuxSysfsLedSmoke.cpp)
    target_link_libraries(pdr-linux-sysfs-led-smoke PRIVATE PocoDDS::LinuxDevices)
    pdr_set_warnings(pdr-linux-sysfs-led-smoke)
    add_test(NAME linux-sysfs-led-smoke COMMAND pdr-linux-sysfs-led-smoke)
endif()

install(TARGETS PDRDeviceLinux ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
