file(GLOB osp_web_sources CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp")
list(REMOVE_ITEM osp_web_sources
    "${CMAKE_CURRENT_SOURCE_DIR}/src/WebBundleActivator.cpp")

add_library(OSPWeb ${osp_web_sources})
add_library(Poco::OSPWeb ALIAS OSPWeb)
set_target_properties(OSPWeb PROPERTIES
    OUTPUT_NAME PocoOSPWeb
    DEFINE_SYMBOL OSPWeb_EXPORTS)
target_include_directories(OSPWeb
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(OSPWeb
    PUBLIC Poco::OSP Poco::Net Poco::Util Poco::XML Poco::Foundation)
if(PDR_ENABLE_OBSERVABILITY)
    target_link_libraries(OSPWeb PUBLIC PocoDDS::Observability)
    target_compile_definitions(OSPWeb PUBLIC PDR_ENABLE_OBSERVABILITY=1)
endif()
pdr_set_warnings(OSPWeb)

myiot_add_osp_bundle(OSP_Web_Bundle "osp.web"
    SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/src/WebBundleActivator.cpp"
    LINK_LIBS OSPWeb Poco::OSP Poco::Net Poco::Util Poco::XML Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC "${CMAKE_CURRENT_SOURCE_DIR}/WebBundle.bndlspec")
pdr_set_warnings(OSP_Web_Bundle)

install(TARGETS OSPWeb ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
