add_library(PDRApplication INTERFACE)
add_library(PocoDDS::Application ALIAS PDRApplication)

target_include_directories(PDRApplication INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)

if(BUILD_TESTING)
    add_executable(pdr-application-smoke tests/ApplicationSmoke.cpp)
    target_link_libraries(pdr-application-smoke PRIVATE PocoDDS::Application)
    pdr_set_warnings(pdr-application-smoke)
    add_test(NAME application-smoke COMMAND pdr-application-smoke)
endif()

install(TARGETS PDRApplication EXPORT PocoDDSRuntimeTargets)
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
