add_library(PDRDeviceGNSS src/NmeaGnssDevice.cpp)
add_library(PocoDDS::GNSSDevice ALIAS PDRDeviceGNSS)

target_include_directories(PDRDeviceGNSS
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRDeviceGNSS
    PUBLIC PocoDDS::DeviceCore PocoDDS::SerialProtocol Poco::Foundation)
pdr_set_warnings(PDRDeviceGNSS)

if(BUILD_TESTING)
    add_executable(pdr-nmea-gnss-device-smoke tests/NmeaGnssDeviceSmoke.cpp)
    target_link_libraries(pdr-nmea-gnss-device-smoke PRIVATE PocoDDS::GNSSDevice)
    pdr_set_warnings(pdr-nmea-gnss-device-smoke)
    add_test(NAME nmea-gnss-device-smoke COMMAND pdr-nmea-gnss-device-smoke)
endif()

install(TARGETS PDRDeviceGNSS ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
