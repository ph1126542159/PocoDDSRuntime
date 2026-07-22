add_library(PocoDDSOSP
    src/BundleManifest.cpp
    src/DependencyResolver.cpp)
target_include_directories(PocoDDSOSP PUBLIC
    "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
    "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>")
target_link_libraries(PocoDDSOSP PUBLIC PocoDDS::Core)
pdr_set_warnings(PocoDDSOSP)
add_library(PocoDDS::OSP ALIAS PocoDDSOSP)
set_target_properties(PocoDDSOSP PROPERTIES EXPORT_NAME OSP)
install(TARGETS PocoDDSOSP EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
