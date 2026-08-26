myiot_add_osp_bundle(PDR_OutboxRuntime_Bundle "pdr.service.outboxRuntime"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::StoreForwardCore
        PocoDDS::SchedulingConfiguration
        PocoDDS::LifecycleAPI
        Poco::OSP
        Poco::Data
        Poco::DataSQLite
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/OutboxRuntime.bndlspec)
pdr_set_warnings(PDR_OutboxRuntime_Bundle)
