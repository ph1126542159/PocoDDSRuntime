add_library(PDRProtocolCAN
    src/SignalCodec.cpp
    src/SocketCanEndpoint.cpp)
add_library(PocoDDS::CAN ALIAS PDRProtocolCAN)

target_include_directories(PDRProtocolCAN
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)

if(WIN32)
    target_link_libraries(PDRProtocolCAN PRIVATE ws2_32)
endif()
pdr_set_warnings(PDRProtocolCAN)

install(TARGETS PDRProtocolCAN ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
