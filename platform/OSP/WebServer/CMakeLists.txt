myiot_add_osp_bundle(OSP_WebServer_Bundle "osp.web.server"
    SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/src/WebServerBundleActivator.cpp"
    LINK_LIBS OSPWeb Poco::OSP Poco::Net Poco::Util Poco::XML Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC "${CMAKE_CURRENT_SOURCE_DIR}/WebServer.bndlspec")
pdr_set_warnings(OSP_WebServer_Bundle)
