add_library(PDRProtocolUDP
    src/UdpChannel.cpp)
add_library(PocoDDS::UDP ALIAS PDRProtocolUDP)

target_include_directories(PDRProtocolUDP
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)

target_link_libraries(PDRProtocolUDP PUBLIC Poco::Net Poco::Foundation)
pdr_set_warnings(PDRProtocolUDP)
install(TARGETS PDRProtocolUDP ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
