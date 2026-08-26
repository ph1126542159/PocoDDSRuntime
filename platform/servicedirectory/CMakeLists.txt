add_library(PDRServiceDirectoryCore src/Directory.cpp)
add_library(PocoDDS::ServiceDirectoryCore ALIAS PDRServiceDirectoryCore)
set_target_properties(PDRServiceDirectoryCore PROPERTIES
    EXPORT_NAME ServiceDirectoryCore)
target_include_directories(PDRServiceDirectoryCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRServiceDirectoryCore PUBLIC Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRServiceDirectoryCore PUBLIC
        PDR_SERVICE_DIRECTORY_STATIC)
endif()
pdr_set_warnings(PDRServiceDirectoryCore)

add_library(PDRServiceDirectoryAPI INTERFACE)
add_library(PocoDDS::ServiceDirectoryAPI ALIAS PDRServiceDirectoryAPI)
set_target_properties(PDRServiceDirectoryAPI PROPERTIES
    EXPORT_NAME ServiceDirectoryAPI)
target_include_directories(PDRServiceDirectoryAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRServiceDirectoryAPI INTERFACE
    PocoDDS::ServiceDirectoryCore Poco::OSP Poco::Foundation)
target_compile_definitions(PDRServiceDirectoryAPI INTERFACE
    POCO_NO_AUTOMATIC_LIBS)

if(BUILD_TESTING)
    add_executable(pdr-service-directory-smoke
        tests/ServiceDirectorySmoke.cpp)
    target_link_libraries(pdr-service-directory-smoke PRIVATE
        PocoDDS::ServiceDirectoryCore)
    pdr_set_warnings(pdr-service-directory-smoke)
    add_test(NAME service-directory-smoke COMMAND pdr-service-directory-smoke)
    set_tests_properties(service-directory-smoke PROPERTIES
        LABELS "service-directory;routing;membership;reliability;release")
endif()

install(TARGETS PDRServiceDirectoryCore PDRServiceDirectoryAPI
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
