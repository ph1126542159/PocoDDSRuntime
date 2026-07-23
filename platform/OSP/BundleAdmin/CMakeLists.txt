file(GLOB bundle_admin_sources CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp")
myiot_add_osp_bundle(OSP_BundleAdmin_Bundle "com.appinf.osp.bundleadmin"
    SOURCES ${bundle_admin_sources}
    LINK_LIBS OSPWeb Poco::OSP Poco::Net Poco::Util Poco::XML Poco::Foundation
    INCLUDE_DIRS
        ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
    BUNDLE_SPEC "${CMAKE_CURRENT_SOURCE_DIR}/BundleAdmin.bndlspec")
pdr_set_warnings(OSP_BundleAdmin_Bundle)
