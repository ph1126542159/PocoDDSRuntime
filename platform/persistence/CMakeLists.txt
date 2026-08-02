add_library(PDRPersistence INTERFACE)
add_library(PocoDDS::Persistence ALIAS PDRPersistence)
set_target_properties(PDRPersistence PROPERTIES EXPORT_NAME Persistence)
target_include_directories(PDRPersistence INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)

if(BUILD_TESTING)
    add_executable(pdr-persistence-smoke tests/PersistenceSmoke.cpp)
    target_link_libraries(pdr-persistence-smoke PRIVATE PocoDDS::Persistence)
    pdr_set_warnings(pdr-persistence-smoke)
    add_test(NAME persistence-smoke COMMAND pdr-persistence-smoke)
endif()

install(TARGETS PDRPersistence EXPORT PocoDDSRuntimeTargets)
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
