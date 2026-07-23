myiot_add_osp_bundle(OSP_ActiveRecord_Bundle "poco.activerecord"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/ActiveRecordBundleActivator.cpp
    LINK_LIBS Poco::OSP Poco::Util Poco::JSON Poco::XML Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/ActiveRecord.bndlspec
)
