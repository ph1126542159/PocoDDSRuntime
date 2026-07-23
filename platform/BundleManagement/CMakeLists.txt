add_library(PDRBundleManagement SHARED
    src/BundleManager.cpp)
add_library(PocoDDS::BundleManagement ALIAS PDRBundleManagement)

target_include_directories(PDRBundleManagement
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_definitions(PDRBundleManagement
    PRIVATE PDR_BUNDLE_MANAGEMENT_EXPORTS)
target_link_libraries(PDRBundleManagement
    PUBLIC Poco::OSP
    PRIVATE Poco::Foundation)
pdr_set_warnings(PDRBundleManagement)

install(TARGETS PDRBundleManagement
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
