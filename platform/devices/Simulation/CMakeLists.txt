add_library(PDRDeviceSimulation src/SimulatedDevice.cpp)
add_library(PocoDDS::SimulationDevice ALIAS PDRDeviceSimulation)

target_include_directories(PDRDeviceSimulation
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRDeviceSimulation PUBLIC PocoDDS::DeviceCore Poco::Foundation)
pdr_set_warnings(PDRDeviceSimulation)

install(TARGETS PDRDeviceSimulation ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
