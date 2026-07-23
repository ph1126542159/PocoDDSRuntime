add_library(OSPWebEvent
    "${CMAKE_CURRENT_SOURCE_DIR}/src/WebEventService.cpp")
add_library(Poco::OSPWebEvent ALIAS OSPWebEvent)
set_target_properties(OSPWebEvent PROPERTIES
    OUTPUT_NAME PocoOSPWebEvent
    DEFINE_SYMBOL OSPWebEvent_EXPORTS)
target_include_directories(OSPWebEvent
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(OSPWebEvent
    PUBLIC OSPWeb Poco::OSP Poco::Net Poco::Util Poco::XML Poco::Foundation)
pdr_set_warnings(OSPWebEvent)

myiot_add_osp_bundle(OSP_WebEvent_Bundle "com.appinf.osp.webevent"
    SOURCES
        "${CMAKE_CURRENT_SOURCE_DIR}/src/WebEventServiceImpl.cpp"
        "${CMAKE_CURRENT_SOURCE_DIR}/src/WebEventRequestHandler.cpp"
        "${CMAKE_CURRENT_SOURCE_DIR}/src/WebEventBundleActivator.cpp"
    LINK_LIBS OSPWebEvent OSPWeb Poco::OSP Poco::Net Poco::Util Poco::XML Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC "${CMAKE_CURRENT_SOURCE_DIR}/WebEventBundle.bndlspec")
pdr_set_warnings(OSP_WebEvent_Bundle)

install(TARGETS OSPWebEvent ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
