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
target_include_directories(PocoDDSCore PUBLIC
    "$<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>"
    "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>")
pdr_set_warnings(PocoDDSCore)
set_target_properties(PocoDDSCore PROPERTIES EXPORT_NAME Core)
add_library(PocoDDS::Core ALIAS PocoDDSCore)

if(PDR_ENABLE_ADMIN)
    pdr_require_poco()
    add_library(PocoDDSAdmin Admin/AdminHttpServer.cpp)
    target_include_directories(PocoDDSAdmin PUBLIC
        "$<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>")
    target_link_libraries(PocoDDSAdmin PUBLIC PocoDDSCore Poco::Net Poco::JSON)
    pdr_set_warnings(PocoDDSAdmin)
    set_target_properties(PocoDDSAdmin PROPERTIES EXPORT_NAME Admin)
    add_library(PocoDDS::Admin ALIAS PocoDDSAdmin)
endif()

if(PDR_ENABLE_OPENTELEMETRY)
    pdr_require_opentelemetry()
    add_library(PocoDDSObservability Observability/BusinessTracer.cpp)
    target_include_directories(PocoDDSObservability PUBLIC
        "$<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>")
    target_link_libraries(PocoDDSObservability PUBLIC
        opentelemetry-cpp::trace
        opentelemetry-cpp::resources
        opentelemetry-cpp::in_memory_span_exporter)
    pdr_set_warnings(PocoDDSObservability)
    set_target_properties(PocoDDSObservability PROPERTIES EXPORT_NAME Observability)
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
    target_include_directories(PocoDDSFastDDS PUBLIC
        "$<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>")
    target_link_libraries(PocoDDSFastDDS PUBLIC PocoDDSCore fastdds fastcdr)
    pdr_set_warnings(PocoDDSFastDDS)
    set_target_properties(PocoDDSFastDDS PROPERTIES EXPORT_NAME FastDDS)
    add_library(PocoDDS::FastDDS ALIAS PocoDDSFastDDS)
endif()

install(TARGETS PocoDDSCore
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
if(PDR_ENABLE_ADMIN)
    install(TARGETS PocoDDSAdmin EXPORT PocoDDSRuntimeTargets
        ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
endif()
if(PDR_ENABLE_OPENTELEMETRY)
    install(TARGETS PocoDDSObservability EXPORT PocoDDSRuntimeTargets
        ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
endif()
if(PDR_ENABLE_FASTDDS)
    install(TARGETS PocoDDSFastDDS EXPORT PocoDDSRuntimeTargets
        ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
endif()
