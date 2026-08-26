myiot_add_osp_bundle(PDR_ProcessGraphEndpoint_Bundle "pdr.platform.processGraph"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/ProcessGraphEndpoint.cpp
    LINK_LIBS
        Poco::OSPWeb
        PocoDDS::ProcessGraph
        Poco::OSP
        Poco::JSON
        Poco::Net
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/ProcessGraphEndpoint.bndlspec)
pdr_set_warnings(PDR_ProcessGraphEndpoint_Bundle)

if(BUILD_TESTING)
    add_dependencies(PDR_ProcessGraphEndpoint_Bundle_Package
        pdr-subprocess-manager-dependency-smoke)
endif()
