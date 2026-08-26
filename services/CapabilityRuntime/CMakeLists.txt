myiot_add_osp_bundle(PDR_CapabilityRuntime_Bundle "pdr.service.capabilityRuntime"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::CapabilitiesPersistence
        Poco::OSP
        Poco::Data
        Poco::DataSQLite
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/CapabilityRuntime.bndlspec)
pdr_set_warnings(PDR_CapabilityRuntime_Bundle)
