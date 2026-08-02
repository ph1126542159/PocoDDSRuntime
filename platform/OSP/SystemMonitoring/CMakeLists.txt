myiot_add_osp_bundle(PDR_SystemMonitoring_Bundle "pdr.platform.systemMonitoring"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/SystemMonitoring.cpp
    LINK_LIBS
        Poco::OSPWeb
        PocoDDS::ProcessManagement
        PocoDDS::Configuration
        PocoDDS::Security
        PocoDDS::Health
        PocoDDS::Observability
        Poco::OSP
        Poco::JSON
        Poco::Net
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
        ${PROJECT_SOURCE_DIR}/platform/OSP/ManagementAuth/include
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/SystemMonitoring.bndlspec)
target_link_libraries(PDR_SystemMonitoring_Bundle PRIVATE PocoDDS::DeviceCore)
target_include_directories(PDR_SystemMonitoring_Bundle PRIVATE
    "${PROJECT_SOURCE_DIR}/platform/protocols/include")
target_compile_definitions(PDR_SystemMonitoring_Bundle PRIVATE
    PDR_RUNTIME_VERSION="${PROJECT_VERSION}"
    PDR_PLUGIN_API_VERSION="${PDR_PLUGIN_API_VERSION}"
    PDR_PLUGIN_ABI_VERSION="${PDR_PLUGIN_ABI_VERSION}"
    PDR_PLUGIN_ABI_FINGERPRINT="${PDR_PLUGIN_ABI_FINGERPRINT}")
pdr_set_warnings(PDR_SystemMonitoring_Bundle)

if(WIN32)
    target_link_libraries(PDR_SystemMonitoring_Bundle PRIVATE iphlpapi psapi)
endif()
