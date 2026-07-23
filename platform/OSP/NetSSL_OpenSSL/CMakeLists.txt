myiot_add_osp_bundle(OSP_NetSSL_Bundle "poco.net.ssl"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/NetSSLBundleActivator.cpp
    LINK_LIBS Poco::OSP Poco::NetSSL Poco::Net Poco::Util Poco::XML Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/NetSSL_OpenSSL.bndlspec
)
