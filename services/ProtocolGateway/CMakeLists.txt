myiot_add_osp_bundle(PDR_ProtocolGateway_Bundle "pdr.protocol.gateway"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::Configuration
        PocoDDS::GatewayAPI
        Poco::OSP
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/ProtocolGateway.bndlspec)

pdr_set_warnings(PDR_ProtocolGateway_Bundle)
