add_library(PDRResourceGovernanceAPI src/ManagedWorkLane.cpp)
add_library(PocoDDS::ResourceGovernanceAPI ALIAS PDRResourceGovernanceAPI)
set_target_properties(PDRResourceGovernanceAPI PROPERTIES EXPORT_NAME ResourceGovernanceAPI)
target_include_directories(PDRResourceGovernanceAPI PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRResourceGovernanceAPI PUBLIC Poco::OSP Poco::Foundation)
target_compile_definitions(PDRResourceGovernanceAPI PUBLIC POCO_NO_AUTOMATIC_LIBS)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRResourceGovernanceAPI PUBLIC
        PDR_RESOURCE_GOVERNANCE_STATIC PDR_RESOURCE_GOVERNANCE_OSP_STATIC)
endif()

add_library(PDRResourceGovernanceCore src/ResourceGovernor.cpp)
add_library(PocoDDS::ResourceGovernanceCore ALIAS PDRResourceGovernanceCore)
set_target_properties(PDRResourceGovernanceCore PROPERTIES EXPORT_NAME ResourceGovernanceCore)
target_include_directories(PDRResourceGovernanceCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRResourceGovernanceCore PUBLIC Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRResourceGovernanceCore PUBLIC PDR_RESOURCE_GOVERNANCE_STATIC)
endif()
pdr_set_warnings(PDRResourceGovernanceCore)

target_link_libraries(PDRResourceGovernanceAPI PUBLIC
    PocoDDS::ResourceGovernanceCore)
pdr_set_warnings(PDRResourceGovernanceAPI)
target_link_libraries(PDRPlugins INTERFACE PocoDDS::ResourceGovernanceAPI)
target_link_libraries(PDRSDK INTERFACE PocoDDS::ResourceGovernanceCore)

if(BUILD_TESTING)
    add_executable(pdr-resource-governor-smoke tests/ResourceGovernorSmoke.cpp)
    target_link_libraries(pdr-resource-governor-smoke PRIVATE
        PocoDDS::ResourceGovernanceCore)
    pdr_set_warnings(pdr-resource-governor-smoke)
    add_test(NAME resource-governor-smoke COMMAND pdr-resource-governor-smoke)
    set_tests_properties(resource-governor-smoke PROPERTIES
        LABELS "resource-governance;concurrency;backpressure;fault-injection;release")

    add_executable(pdr-managed-work-lane-smoke tests/ManagedWorkLaneSmoke.cpp)
    target_link_libraries(pdr-managed-work-lane-smoke PRIVATE
        PocoDDS::ResourceGovernanceAPI)
    pdr_set_warnings(pdr-managed-work-lane-smoke)
    add_test(NAME managed-work-lane-smoke COMMAND pdr-managed-work-lane-smoke)
    set_tests_properties(managed-work-lane-smoke PROPERTIES
        LABELS "resource-governance;bundle;lifecycle;backpressure;release")
endif()

install(TARGETS PDRResourceGovernanceAPI PDRResourceGovernanceCore
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
