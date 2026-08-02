myiot_add_osp_bundle(PDR_ManagementAuth_Bundle "pdr.platform.managementAuth"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/ManagementAuth.cpp
    LINK_LIBS
        PocoDDS::Security
        Poco::OSPWeb
        Poco::OSP
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/ManagementAuth.bndlspec)
pdr_set_warnings(PDR_ManagementAuth_Bundle)
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
