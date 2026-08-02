add_library(PDRProtocolXBee
    src/IoSample.cpp
    src/XBeeFrame.cpp
    src/XBeePort.cpp)
add_library(PocoDDS::XBee ALIAS PDRProtocolXBee)

target_include_directories(PDRProtocolXBee
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)

target_link_libraries(PDRProtocolXBee
    PUBLIC PocoDDS::SerialProtocol Poco::Foundation)
pdr_set_warnings(PDRProtocolXBee)
set_target_properties(PDRProtocolXBee PROPERTIES EXPORT_NAME XBee)

if(BUILD_TESTING)
    add_executable(pdr-xbee-smoke tests/XBeeSmoke.cpp)
    target_link_libraries(pdr-xbee-smoke PRIVATE PocoDDS::XBee)
    pdr_set_warnings(pdr-xbee-smoke)
    add_test(NAME xbee-smoke COMMAND pdr-xbee-smoke)
endif()

install(TARGETS PDRProtocolXBee EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
