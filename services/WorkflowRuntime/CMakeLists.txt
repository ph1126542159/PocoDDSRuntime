myiot_add_osp_bundle(PDR_WorkflowRuntime_Bundle "pdr.service.workflowRuntime"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::WorkflowCore
        PocoDDS::SchedulingConfiguration
        PocoDDS::LifecycleAPI
        Poco::OSP
        Poco::Data
        Poco::DataSQLite
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/WorkflowRuntime.bndlspec)
pdr_set_warnings(PDR_WorkflowRuntime_Bundle)
