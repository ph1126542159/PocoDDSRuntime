myiot_add_osp_bundle(PDR_BuiltinDeviceFactories_Bundle "pdr.device.factories.builtin"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::Devices
        PocoDDS::GatewayAPI
        Poco::OSP
        Poco::Util
        Poco::Net
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/BuiltinDeviceFactories.bndlspec)

pdr_set_warnings(PDR_BuiltinDeviceFactories_Bundle)
