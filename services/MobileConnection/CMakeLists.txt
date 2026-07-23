add_library(PDRMobileConnection
    src/MobileConnectionService.cpp
    src/MemoryMobileConnectionService.cpp
    backends/Legato/MobileConnectionServiceImpl.cpp)
target_include_directories(PDRMobileConnection
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRMobileConnection PUBLIC Poco::OSP Poco::Util Poco::Foundation)
pdr_set_warnings(PDRMobileConnection)

myiot_add_osp_bundle(PDR_MobileConnection_Bundle "pdr.service.mobile"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PDRMobileConnection
        PocoDDS::FastDDS
        Poco::OSP
        Poco::JSON
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/MobileConnection.bndlspec)
pdr_set_warnings(PDR_MobileConnection_Bundle)

if(BUILD_TESTING)
    add_executable(pdr-mobile-connection-smoke tests/MobileConnectionSmoke.cpp)
    target_link_libraries(pdr-mobile-connection-smoke PRIVATE PDRMobileConnection)
    pdr_set_warnings(pdr-mobile-connection-smoke)
    add_test(NAME mobile-connection-smoke COMMAND pdr-mobile-connection-smoke)
endif()

install(TARGETS PDRMobileConnection ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
