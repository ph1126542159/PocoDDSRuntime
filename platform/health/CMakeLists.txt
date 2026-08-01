add_library(PDRHealth INTERFACE)
add_library(PocoDDS::Health ALIAS PDRHealth)
set_target_properties(PDRHealth PROPERTIES EXPORT_NAME Health)
target_include_directories(PDRHealth INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)

if(BUILD_TESTING)
    add_executable(pdr-health-smoke tests/HealthSmoke.cpp)
    target_link_libraries(pdr-health-smoke PRIVATE PocoDDS::Health)
    pdr_set_warnings(pdr-health-smoke)
    add_test(NAME health-smoke COMMAND pdr-health-smoke)
endif()

install(TARGETS PDRHealth EXPORT PocoDDSRuntimeTargets)
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
