myiot_add_osp_bundle(PDR_SystemMonitoring_Bundle "pdr.platform.systemMonitoring"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/SystemMonitoring.cpp
    LINK_LIBS
        Poco::OSPWeb
        PocoDDS::ProcessManagement
        PocoDDS::Observability
        Poco::OSP
        Poco::JSON
        Poco::Net
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/SystemMonitoring.bndlspec)
pdr_set_warnings(PDR_SystemMonitoring_Bundle)

if(WIN32)
    target_link_libraries(PDR_SystemMonitoring_Bundle PRIVATE iphlpapi psapi)
endif()
