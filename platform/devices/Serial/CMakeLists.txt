add_library(PDRDeviceSerial src/SerialPortDevice.cpp)
add_library(PocoDDS::SerialDevice ALIAS PDRDeviceSerial)

target_include_directories(PDRDeviceSerial
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRDeviceSerial
    PUBLIC PocoDDS::DeviceCore PocoDDS::SerialProtocol Poco::Foundation)
pdr_set_warnings(PDRDeviceSerial)

install(TARGETS PDRDeviceSerial ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
