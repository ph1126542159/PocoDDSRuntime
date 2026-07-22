add_library(PocoDDSOSP
    src/BundleManifest.cpp
    src/DependencyResolver.cpp)
target_include_directories(PocoDDSOSP PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(PocoDDSOSP PUBLIC PocoDDS::Core)
pdr_set_warnings(PocoDDSOSP)
add_library(PocoDDS::OSP ALIAS PocoDDSOSP)

