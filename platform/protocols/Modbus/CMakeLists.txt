add_library(PDRProtocolModbus
    src/ModbusTcpClient.cpp
    src/ModbusTcpCodec.cpp)
add_library(PocoDDS::Modbus ALIAS PDRProtocolModbus)

target_include_directories(PDRProtocolModbus
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)

pdr_set_warnings(PDRProtocolModbus)
target_link_libraries(PDRProtocolModbus
    PUBLIC Poco::Net Poco::Foundation)
install(TARGETS PDRProtocolModbus ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
