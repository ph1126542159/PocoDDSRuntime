add_library(PDRDeviceCore src/Device.cpp)
add_library(PocoDDS::DeviceCore ALIAS PDRDeviceCore)

target_include_directories(PDRDeviceCore
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRDeviceCore PUBLIC Poco::Foundation)
pdr_set_warnings(PDRDeviceCore)

if(BUILD_TESTING)
    add_executable(pdr-device-interfaces-smoke
        tests/DeviceInterfacesSmoke.cpp)
    target_link_libraries(pdr-device-interfaces-smoke PRIVATE PocoDDS::DeviceCore)
    pdr_set_warnings(pdr-device-interfaces-smoke)
    add_test(NAME device-interfaces-smoke COMMAND pdr-device-interfaces-smoke)
endif()

install(TARGETS PDRDeviceCore ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
