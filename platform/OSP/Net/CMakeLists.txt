myiot_add_osp_bundle(OSP_Net_Bundle "poco.net"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/NetBundleActivator.cpp
    LINK_LIBS Poco::OSP Poco::Net Poco::Util Poco::XML Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/Net.bndlspec
)
