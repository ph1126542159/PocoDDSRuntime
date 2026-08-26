myiot_add_osp_bundle(PDR_TransportRegistryRuntime_Bundle "pdr.service.transportRegistry"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::TransportProviderCore
        Poco::OSP
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/TransportRegistryRuntime.bndlspec)
pdr_set_warnings(PDR_TransportRegistryRuntime_Bundle)
