add_library(PDRProtocolSerial
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

install(TARGETS PDRProtocolSerial ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
