myiot_add_osp_bundle(OSP_SimpleAuth_Bundle "com.appinf.osp.simple-auth"
    SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/src/SimpleAuth.cpp"
    LINK_LIBS Poco::OSP Poco::JSON Poco::Util Poco::XML Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC "${CMAKE_CURRENT_SOURCE_DIR}/SimpleAuth.bndlspec")
pdr_set_warnings(OSP_SimpleAuth_Bundle)
