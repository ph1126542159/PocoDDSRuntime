myiot_add_osp_bundle(PDR_CapabilityManagement_Bundle "pdr.service.capabilityManagement"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/CapabilityManagement.cpp
    LINK_LIBS
        PocoDDS::CapabilitiesCore
        PocoDDS::Security
        Poco::OSPWeb
        Poco::OSP
        Poco::JSON
        Poco::Net
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
        ${PROJECT_SOURCE_DIR}/platform/OSP/ManagementAuth/include
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/CapabilityManagement.bndlspec)
pdr_set_warnings(PDR_CapabilityManagement_Bundle)

