add_library(PDRSDK INTERFACE)
add_library(PocoDDS::SDK ALIAS PDRSDK)
set_target_properties(PDRSDK PROPERTIES EXPORT_NAME SDK)

target_include_directories(PDRSDK INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRSDK INTERFACE
    PocoDDS::Application
    PocoDDS::Configuration
    PocoDDS::DeviceCore
    PocoDDS::Reliability
    PocoDDS::Health
    PocoDDS::Persistence)

configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/include/PocoDDS/SDK/Version.h.in"
    "${CMAKE_CURRENT_BINARY_DIR}/include/PocoDDS/SDK/Version.h"
    @ONLY)

install(TARGETS PDRSDK EXPORT PocoDDSRuntimeTargets)
install(FILES
    "${CMAKE_CURRENT_SOURCE_DIR}/include/PocoDDS/SDK/SDK.h"
    "${CMAKE_CURRENT_BINARY_DIR}/include/PocoDDS/SDK/Version.h"
    DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}/PocoDDS/SDK")
