myiot_add_osp_bundle(PDR_LifecycleRuntime_Bundle
    "pdr.service.lifecycleRuntime"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::LifecycleAPI
        PocoDDS::LifecyclePersistence
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
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/LifecycleRuntime.bndlspec)
pdr_set_warnings(PDR_LifecycleRuntime_Bundle)
