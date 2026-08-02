add_library(PDRProtocolBtLE INTERFACE)
add_library(PocoDDS::BtLE ALIAS PDRProtocolBtLE)

target_include_directories(PDRProtocolBtLE
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRProtocolBtLE INTERFACE Poco::Foundation)
set_target_properties(PDRProtocolBtLE PROPERTIES EXPORT_NAME BtLE)

if(BUILD_TESTING)
    add_executable(pdr-btle-smoke tests/BtLESmoke.cpp)
    target_link_libraries(pdr-btle-smoke PRIVATE PocoDDS::BtLE)
    pdr_set_warnings(pdr-btle-smoke)
    add_test(NAME btle-smoke COMMAND pdr-btle-smoke)
endif()

install(TARGETS PDRProtocolBtLE EXPORT PocoDDSRuntimeTargets)
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
