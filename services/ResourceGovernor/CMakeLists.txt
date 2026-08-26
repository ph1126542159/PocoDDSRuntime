myiot_add_osp_bundle(PDR_ResourceGovernor_Bundle "pdr.service.resourceGovernor"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/ResourceGovernorBundle.cpp
    LINK_LIBS
        PocoDDS::ResourceGovernanceCore
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
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/ResourceGovernor.bndlspec)
pdr_set_warnings(PDR_ResourceGovernor_Bundle)
