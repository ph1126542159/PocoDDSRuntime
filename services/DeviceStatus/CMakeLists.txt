add_library(PDRDeviceStatus
    src/DeviceStatusService.cpp
    src/DeviceStatusServiceImpl.cpp)
target_include_directories(PDRDeviceStatus
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRDeviceStatus
    PUBLIC Poco::OSP Poco::Data Poco::DataSQLite Poco::Foundation)
pdr_set_warnings(PDRDeviceStatus)

myiot_add_osp_bundle(PDR_DeviceStatus_Bundle "pdr.service.deviceStatus"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PDRDeviceStatus
        PocoDDS::FastDDS
        Poco::OSP
        Poco::Data
        Poco::DataSQLite
        Poco::JSON
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/DeviceStatus.bndlspec)
pdr_set_warnings(PDR_DeviceStatus_Bundle)

if(BUILD_TESTING)
    add_executable(pdr-device-status-smoke tests/DeviceStatusSmoke.cpp)
    target_link_libraries(pdr-device-status-smoke
        PRIVATE PDRDeviceStatus Poco::DataSQLite)
    pdr_set_warnings(pdr-device-status-smoke)
    add_test(NAME device-status-smoke COMMAND pdr-device-status-smoke)
endif()

install(TARGETS PDRDeviceStatus ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
