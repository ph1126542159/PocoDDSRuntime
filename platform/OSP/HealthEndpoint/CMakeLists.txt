myiot_add_osp_bundle(PDR_HealthEndpoint_Bundle "pdr.platform.health"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/HealthEndpoint.cpp
    LINK_LIBS
        Poco::OSPWeb
        PocoDDS::ProcessManagement
        PocoDDS::Health
        PocoDDS::DeviceCore
        PocoDDS::Protocols
        Poco::OSP
        Poco::JSON
        Poco::Net
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/HealthEndpoint.bndlspec)
pdr_set_warnings(PDR_HealthEndpoint_Bundle)
if(PDR_ENABLE_OBSERVABILITY)
    target_link_libraries(PDR_HealthEndpoint_Bundle PRIVATE PocoDDS::Observability)
    target_compile_definitions(PDR_HealthEndpoint_Bundle PRIVATE PDR_HEALTH_METRICS=1)
endif()
