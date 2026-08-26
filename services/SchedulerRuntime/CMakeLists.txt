myiot_add_osp_bundle(PDR_SchedulerRuntime_Bundle "pdr.service.schedulerRuntime"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/SchedulerRuntimeBundle.cpp
    LINK_LIBS
        PocoDDS::SchedulingCore
        PocoDDS::ResourceGovernanceAPI
        PocoDDS::Security
        Poco::OSPWeb
        Poco::OSP
        Poco::JSON
        Poco::Net
        Poco::Foundation
    INCLUDE_DIRS
        ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
        ${CMAKE_SOURCE_DIR}/platform/OSP/ManagementAuth/include
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/SchedulerRuntime.bndlspec)
pdr_set_warnings(PDR_SchedulerRuntime_Bundle)
