add_executable(PocoDDSCoreTests
    BundleManagerTest.cpp
    ComponentRegistryTest.cpp
    InMemoryTransportTest.cpp)
target_link_libraries(PocoDDSCoreTests PRIVATE PocoDDS::Core GTest::gtest_main)
pdr_set_warnings(PocoDDSCoreTests)
include(GoogleTest)
gtest_discover_tests(PocoDDSCoreTests)

