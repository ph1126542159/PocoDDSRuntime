myiot_add_osp_bundle(PDR_ServiceDependencyRuntime_Bundle
    "pdr.service.serviceDependencyRuntime"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::ServiceDependencyAPI
        PocoDDS::Health
        PocoDDS::Security
        Poco::OSPWeb
        Poco::OSP
        Poco::JSON
        Poco::Net
        Poco::Foundation
    INCLUDE_DIRS
        ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
        ${CMAKE_SOURCE_DIR}/platform/OSP/ManagementAuth/include
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/ServiceDependencyRuntime.bndlspec)
pdr_set_warnings(PDR_ServiceDependencyRuntime_Bundle)
