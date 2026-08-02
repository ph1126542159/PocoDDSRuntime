myiot_add_osp_bundle(PDR_ProtocolGateway_Bundle "pdr.protocol.gateway"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::MQTT
        PocoDDS::ROS
        PocoDDS::UDP
        PocoDDS::Configuration
        Poco::OSP
        Poco::Util
        Poco::Net
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/ProtocolGateway.bndlspec)

pdr_set_warnings(PDR_ProtocolGateway_Bundle)
