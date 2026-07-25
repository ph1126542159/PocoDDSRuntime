add_library(PDRConfiguration src/ConfigurationValidator.cpp)
add_library(PocoDDS::Configuration ALIAS PDRConfiguration)
target_include_directories(PDRConfiguration PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRConfiguration PUBLIC Poco::Util Poco::Foundation)
pdr_set_warnings(PDRConfiguration)

if(BUILD_TESTING)
    add_executable(pdr-configuration-smoke tests/ConfigurationSmoke.cpp)
    target_link_libraries(pdr-configuration-smoke PRIVATE PocoDDS::Configuration)
    pdr_set_warnings(pdr-configuration-smoke)
    add_test(NAME configuration-smoke COMMAND pdr-configuration-smoke)
endif()

install(TARGETS PDRConfiguration
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
