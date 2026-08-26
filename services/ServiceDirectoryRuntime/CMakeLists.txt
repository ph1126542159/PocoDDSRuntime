myiot_add_osp_bundle(PDR_ServiceDirectoryRuntime_Bundle
    "pdr.service.serviceDirectoryRuntime"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::ServiceDirectoryAPI
        PocoDDS::MembershipAPI
        PocoDDS::FastDDS
        PocoDDS::Health
        PocoDDS::Security
        Poco::OSPWeb
        Poco::OSP
        Poco::JSON
        Poco::Net
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS
        ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
        ${CMAKE_SOURCE_DIR}/platform/OSP/ManagementAuth/include
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/ServiceDirectoryRuntime.bndlspec)
pdr_set_warnings(PDR_ServiceDirectoryRuntime_Bundle)
