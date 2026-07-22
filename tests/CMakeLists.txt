add_executable(PocoDDSCoreTests
    AdminServiceTest.cpp
    BundleManagerTest.cpp
    ContractCodecTest.cpp
    ControlPlaneAgentTest.cpp
    ContractGeneratorTest.cpp
    DependencyResolverTest.cpp
    DiscoveryAgentTest.cpp
    ComponentRegistryTest.cpp
    ConfigurationTest.cpp
    InMemoryTransportTest.cpp)
target_sources(PocoDDSCoreTests PRIVATE SupervisorTest.cpp)
add_executable(pdr-test-child TestChild.cpp)
pdr_set_warnings(pdr-test-child)
add_library(pdr-test-bundle SHARED TestDynamicBundle.cpp)
target_include_directories(pdr-test-bundle PRIVATE "${PROJECT_SOURCE_DIR}/include")
pdr_set_warnings(pdr-test-bundle)
target_compile_definitions(PocoDDSCoreTests PRIVATE
    PDR_TEST_CHILD_PATH="$<TARGET_FILE:pdr-test-child>"
    PDR_TEST_BUNDLE_PATH="$<TARGET_FILE:pdr-test-bundle>")
add_dependencies(PocoDDSCoreTests pdr-test-child pdr-test-bundle)
if(PDR_ENABLE_FASTDDS)
    target_sources(PocoDDSCoreTests PRIVATE FastDDSMultiProcessTest.cpp)
    target_compile_definitions(PocoDDSCoreTests PRIVATE
        PDR_DDS_PROBE_PATH="$<TARGET_FILE:pdr-dds-probe>")
    add_dependencies(PocoDDSCoreTests pdr-dds-probe)
endif()
if(PDR_ENABLE_OPENTELEMETRY)
    target_sources(PocoDDSCoreTests PRIVATE BusinessTracerTest.cpp)
    target_link_libraries(PocoDDSCoreTests PRIVATE PocoDDS::Observability)
endif()
if(PDR_ENABLE_ADMIN)
    target_sources(PocoDDSCoreTests PRIVATE AdminHttpServerTest.cpp)
    target_link_libraries(PocoDDSCoreTests PRIVATE PocoDDS::Admin)
endif()
target_link_libraries(PocoDDSCoreTests PRIVATE PocoDDS::Core PocoDDS::OSP
    PocoDDS::CodeGeneration GTest::gtest_main)
pdr_set_warnings(PocoDDSCoreTests)
include(GoogleTest)
gtest_discover_tests(PocoDDSCoreTests)
