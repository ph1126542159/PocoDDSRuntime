add_executable(pdr-runtime RuntimeMain.cpp)
target_link_libraries(pdr-runtime PRIVATE PocoDDS::Core)
pdr_set_warnings(pdr-runtime)

if(PDR_ENABLE_FASTDDS)
    add_executable(pdr-dds-probe FastDDSProbe.cpp)
    target_link_libraries(pdr-dds-probe PRIVATE PocoDDSFastDDS)
    pdr_set_warnings(pdr-dds-probe)
endif()
