set(PDR_BUILTIN_TRANSPORT_LIBRARIES
    PocoDDS::TransportProviderAPI
    Poco::OSP
    Poco::Foundation)
set(PDR_BUILTIN_TRANSPORT_DEFINITIONS)

if(TARGET PDRMqttTransport)
    list(APPEND PDR_BUILTIN_TRANSPORT_LIBRARIES PocoDDS::MQTTTransport)
    list(APPEND PDR_BUILTIN_TRANSPORT_DEFINITIONS PDR_HAS_MQTT_TRANSPORT=1)
endif()
if(TARGET PDRFastDdsTransport)
    list(APPEND PDR_BUILTIN_TRANSPORT_LIBRARIES PocoDDS::FastDDSTransport)
    list(APPEND PDR_BUILTIN_TRANSPORT_DEFINITIONS PDR_HAS_FASTDDS_TRANSPORT=1)
endif()

myiot_add_osp_bundle(PDR_BuiltinTransportFactories_Bundle "pdr.transport.factories.builtin"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS ${PDR_BUILTIN_TRANSPORT_LIBRARIES}
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/BuiltinTransportFactories.bndlspec)
target_compile_definitions(PDR_BuiltinTransportFactories_Bundle PRIVATE
    ${PDR_BUILTIN_TRANSPORT_DEFINITIONS})
pdr_set_warnings(PDR_BuiltinTransportFactories_Bundle)
