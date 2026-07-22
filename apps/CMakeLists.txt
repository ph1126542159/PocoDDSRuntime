add_executable(pdr-runtime RuntimeMain.cpp)
target_link_libraries(pdr-runtime PRIVATE PocoDDS::Core)
pdr_set_warnings(pdr-runtime)

