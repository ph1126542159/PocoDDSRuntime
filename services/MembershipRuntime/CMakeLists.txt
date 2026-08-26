myiot_add_osp_bundle(PDR_MembershipRuntime_Bundle
    "pdr.service.membershipRuntime"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::MembershipAPI
        PocoDDS::MembershipPersistence
        PocoDDS::FastDDS
        PocoDDS::Health
        Poco::OSP
        Poco::JSON
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/MembershipRuntime.bndlspec)
pdr_set_warnings(PDR_MembershipRuntime_Bundle)
