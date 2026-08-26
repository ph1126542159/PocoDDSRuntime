myiot_add_osp_bundle(PDR_SchemaRegistryRuntime_Bundle "pdr.service.schemaRegistry"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::SchemaRegistryCore
        PocoDDS::CapabilitiesAPI
        Poco::OSP
        Poco::Data
        Poco::DataSQLite
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/SchemaRegistryRuntime.bndlspec)
pdr_set_warnings(PDR_SchemaRegistryRuntime_Bundle)
