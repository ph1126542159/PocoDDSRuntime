add_library(PocoDDSCore
    Core/BundleManager.cpp
    Core/Configuration.cpp
    Core/ComponentRegistry.cpp
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

if(PDR_ENABLE_FASTDDS)
    pdr_require_fastdds()
    add_library(PocoDDSFastDDS Transport/FastDDSTransport.cpp)
    target_include_directories(PocoDDSFastDDS PUBLIC "${PROJECT_SOURCE_DIR}/include")
    target_link_libraries(PocoDDSFastDDS PUBLIC PocoDDSCore fastdds)
    pdr_set_warnings(PocoDDSFastDDS)
endif()
