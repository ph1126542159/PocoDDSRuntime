myiot_add_osp_bundle(OSP_Data_Bundle "poco.data"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/DataBundleActivator.cpp
    LINK_LIBS Poco::OSP Poco::Data Poco::Util Poco::XML Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/Data.bndlspec
)

add_subdirectory(SQLite)
