myiot_add_osp_bundle(OSP_Core_Bundle "osp.core"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/CoreBundleActivator.cpp
    LINK_LIBS Poco::OSP Poco::Util Poco::XML Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/Core.bndlspec
)
