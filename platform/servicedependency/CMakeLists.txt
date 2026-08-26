add_library(PDRServiceDependencyCore src/ServiceDependency.cpp)
add_library(PocoDDS::ServiceDependencyCore ALIAS PDRServiceDependencyCore)
set_target_properties(PDRServiceDependencyCore PROPERTIES EXPORT_NAME ServiceDependencyCore)
target_include_directories(PDRServiceDependencyCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRServiceDependencyCore PUBLIC PDR_SERVICE_DEPENDENCY_STATIC)
endif()
pdr_set_warnings(PDRServiceDependencyCore)

add_library(PDRServiceDependencyAPI INTERFACE)
add_library(PocoDDS::ServiceDependencyAPI ALIAS PDRServiceDependencyAPI)
set_target_properties(PDRServiceDependencyAPI PROPERTIES EXPORT_NAME ServiceDependencyAPI)
target_include_directories(PDRServiceDependencyAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRServiceDependencyAPI INTERFACE
    PocoDDS::ServiceDependencyCore Poco::OSP Poco::Foundation)
target_compile_definitions(PDRServiceDependencyAPI INTERFACE POCO_NO_AUTOMATIC_LIBS)

target_link_libraries(PDRPlugins INTERFACE PocoDDS::ServiceDependencyAPI)
target_link_libraries(PDRSDK INTERFACE PocoDDS::ServiceDependencyCore)

if(BUILD_TESTING)
    add_executable(pdr-service-dependency-smoke tests/ServiceDependencySmoke.cpp)
    target_link_libraries(pdr-service-dependency-smoke PRIVATE
        PocoDDS::ServiceDependencyCore)
    pdr_set_warnings(pdr-service-dependency-smoke)
    add_test(NAME service-dependency-smoke COMMAND pdr-service-dependency-smoke)
    set_tests_properties(service-dependency-smoke PROPERTIES
        LABELS "architecture;service;dependency;readiness;concurrency;release")
endif()

install(TARGETS PDRServiceDependencyCore PDRServiceDependencyAPI
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
