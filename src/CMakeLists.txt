add_library(PocoDDSCore
    Admin/AdminService.cpp
    Control/ContractCodec.cpp
    Control/ControlPlaneClient.cpp
    Control/ControlPlaneAgent.cpp
    Control/DiscoveryAgent.cpp
    Core/BundleManager.cpp
    Core/BundleDirectoryWatcher.cpp
    Core/Configuration.cpp
    Core/ComponentRegistry.cpp
    Core/DynamicBundle.cpp
    Supervisor/Supervisor.cpp
    Transport/InMemoryTransport.cpp)
if(WIN32)
    target_sources(PocoDDSCore PRIVATE Supervisor/NativeProcessWindows.cpp)
else()
    target_sources(PocoDDSCore PRIVATE Supervisor/NativeProcessPosix.cpp)
endif()
target_include_directories(PocoDDSCore PUBLIC "${PROJECT_SOURCE_DIR}/include")
pdr_set_warnings(PocoDDSCore)
add_library(PocoDDS::Core ALIAS PocoDDSCore)

if(PDR_ENABLE_ADMIN)
    pdr_require_poco()
    add_library(PocoDDSAdmin Admin/AdminHttpServer.cpp)
    target_include_directories(PocoDDSAdmin PUBLIC "${PROJECT_SOURCE_DIR}/include")
    target_link_libraries(PocoDDSAdmin PUBLIC PocoDDSCore Poco::Net Poco::JSON)
    pdr_set_warnings(PocoDDSAdmin)
    add_library(PocoDDS::Admin ALIAS PocoDDSAdmin)
endif()

if(PDR_ENABLE_OPENTELEMETRY)
    pdr_require_opentelemetry()
    add_library(PocoDDSObservability Observability/BusinessTracer.cpp)
    target_include_directories(PocoDDSObservability PUBLIC "${PROJECT_SOURCE_DIR}/include")
    target_link_libraries(PocoDDSObservability PUBLIC
        opentelemetry-cpp::trace
        opentelemetry-cpp::resources
        opentelemetry-cpp::in_memory_span_exporter)
    pdr_set_warnings(PocoDDSObservability)
    add_library(PocoDDS::Observability ALIAS PocoDDSObservability)
    if(PDR_ENABLE_OTLP_HTTP)
        pdr_require_poco()
        target_sources(PocoDDSObservability PRIVATE Observability/OtlpHttpJsonExporter.cpp)
        target_link_libraries(PocoDDSObservability PUBLIC Poco::Net Poco::JSON)
        target_compile_definitions(PocoDDSObservability PRIVATE PDR_ENABLE_OTLP_HTTP=1)
    endif()
endif()

if(PDR_ENABLE_FASTDDS)
    pdr_require_fastdds()
    add_library(PocoDDSFastDDS Transport/FastDDSTransport.cpp)
    target_include_directories(PocoDDSFastDDS PUBLIC "${PROJECT_SOURCE_DIR}/include")
    target_link_libraries(PocoDDSFastDDS PUBLIC PocoDDSCore fastdds fastcdr)
    pdr_set_warnings(PocoDDSFastDDS)
endif()
