myiot_add_osp_bundle(PDR_BuiltinProtocolFactories_Bundle "pdr.protocol.factories.builtin"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::MQTT
        PocoDDS::ROS
        PocoDDS::UDP
        PocoDDS::GatewayAPI
        Poco::OSP
        Poco::Util
        Poco::Net
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/BuiltinProtocolFactories.bndlspec)

pdr_set_warnings(PDR_BuiltinProtocolFactories_Bundle)
