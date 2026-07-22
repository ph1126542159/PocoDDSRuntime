add_executable(PocoDDSCoreTests
    BundleManagerTest.cpp
    ContractGeneratorTest.cpp
    DependencyResolverTest.cpp
    ComponentRegistryTest.cpp
    ConfigurationTest.cpp
    InMemoryTransportTest.cpp)
target_sources(PocoDDSCoreTests PRIVATE SupervisorTest.cpp)
add_executable(pdr-test-child TestChild.cpp)
pdr_set_warnings(pdr-test-child)
target_compile_definitions(PocoDDSCoreTests PRIVATE
    PDR_TEST_CHILD_PATH="$<TARGET_FILE:pdr-test-child>")
add_dependencies(PocoDDSCoreTests pdr-test-child)
target_link_libraries(PocoDDSCoreTests PRIVATE PocoDDS::Core PocoDDS::OSP
    PocoDDS::CodeGeneration GTest::gtest_main)
pdr_set_warnings(PocoDDSCoreTests)
include(GoogleTest)
gtest_discover_tests(PocoDDSCoreTests)
