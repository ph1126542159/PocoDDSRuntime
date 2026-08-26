myiot_add_osp_bundle(PDR_DeviceGateway_Bundle "pdr.device.gateway"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::FastDDS
        PocoDDS::DeviceCore
        PocoDDS::Configuration
        PocoDDS::GatewayAPI
        Poco::OSP
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/DeviceGateway.bndlspec)

pdr_set_warnings(PDR_DeviceGateway_Bundle)
