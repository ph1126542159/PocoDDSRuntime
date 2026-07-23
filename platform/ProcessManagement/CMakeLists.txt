add_library(PDRProcessManagement SHARED
    src/SubprocessManager.cpp)
add_library(PocoDDS::ProcessManagement ALIAS PDRProcessManagement)

target_include_directories(PDRProcessManagement
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_definitions(PDRProcessManagement
    PRIVATE PDR_PROCESS_MANAGEMENT_EXPORTS)
target_link_libraries(PDRProcessManagement
    PRIVATE
        Poco::Util
        Poco::Foundation)
pdr_set_warnings(PDRProcessManagement)

install(TARGETS PDRProcessManagement
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
