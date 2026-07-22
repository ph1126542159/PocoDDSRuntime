add_executable(PocoDDSCoreTests
    BundleManagerTest.cpp
    ContractGeneratorTest.cpp
    DependencyResolverTest.cpp
    ComponentRegistryTest.cpp
    InMemoryTransportTest.cpp)
target_link_libraries(PocoDDSCoreTests PRIVATE PocoDDS::Core PocoDDS::OSP
    PocoDDS::CodeGeneration GTest::gtest_main)
pdr_set_warnings(PocoDDSCoreTests)
include(GoogleTest)
gtest_discover_tests(PocoDDSCoreTests)
