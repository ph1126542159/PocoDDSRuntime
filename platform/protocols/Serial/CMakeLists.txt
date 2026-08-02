add_library(PDRProtocolSerial
    src/LoopbackSerialChannel.cpp
    src/SerialChannel.cpp)
add_library(PocoDDS::SerialProtocol ALIAS PDRProtocolSerial)

target_include_directories(PDRProtocolSerial
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)

target_link_libraries(PDRProtocolSerial
    PUBLIC Poco::Serial Poco::Foundation)
pdr_set_warnings(PDRProtocolSerial)
set_target_properties(PDRProtocolSerial PROPERTIES EXPORT_NAME SerialProtocol)

if(BUILD_TESTING)
    add_executable(pdr-serial-loopback-smoke tests/LoopbackSerialTest.cpp)
    target_link_libraries(pdr-serial-loopback-smoke
        PRIVATE PocoDDS::SerialProtocol Poco::Foundation)
    pdr_set_warnings(pdr-serial-loopback-smoke)
    add_test(NAME serial-loopback-smoke COMMAND pdr-serial-loopback-smoke)
    set_tests_properties(serial-loopback-smoke PROPERTIES
        LABELS "protocol;device"
        TIMEOUT 5)
endif()

install(TARGETS PDRProtocolSerial EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
