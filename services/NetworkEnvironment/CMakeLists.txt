add_library(PDRNetworkEnvironment
    src/NetworkEnvironmentService.cpp
    src/NetworkEnvironmentServiceImpl.cpp)
target_include_directories(PDRNetworkEnvironment
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRNetworkEnvironment PUBLIC Poco::OSP Poco::Net Poco::Foundation)
pdr_set_warnings(PDRNetworkEnvironment)

myiot_add_osp_bundle(PDR_NetworkEnvironment_Bundle "pdr.service.network"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PDRNetworkEnvironment
        PocoDDS::FastDDS
        Poco::OSP
        Poco::JSON
        Poco::Util
        Poco::Net
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/NetworkEnvironment.bndlspec)
pdr_set_warnings(PDR_NetworkEnvironment_Bundle)

if(BUILD_TESTING)
    add_executable(pdr-network-environment-smoke
        tests/NetworkEnvironmentSmoke.cpp)
    target_link_libraries(pdr-network-environment-smoke PRIVATE PDRNetworkEnvironment)
    pdr_set_warnings(pdr-network-environment-smoke)
    add_test(NAME network-environment-smoke COMMAND pdr-network-environment-smoke)
endif()

install(TARGETS PDRNetworkEnvironment ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
