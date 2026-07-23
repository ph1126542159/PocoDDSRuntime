add_library(PDRProtocolROS
    src/BridgeClient.cpp)
add_library(PocoDDS::ROS ALIAS PDRProtocolROS)

target_include_directories(PDRProtocolROS
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRProtocolROS PUBLIC Poco::Foundation Poco::JSON Poco::Net)
pdr_set_warnings(PDRProtocolROS)

if(BUILD_TESTING)
    add_executable(pdr-ros-smoke tests/RosSmoke.cpp)
    target_link_libraries(pdr-ros-smoke PRIVATE PocoDDS::ROS)
    pdr_set_warnings(pdr-ros-smoke)
    add_test(NAME ros-smoke COMMAND pdr-ros-smoke)
endif()

install(TARGETS PDRProtocolROS ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
