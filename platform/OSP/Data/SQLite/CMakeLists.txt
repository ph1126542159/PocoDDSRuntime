myiot_add_osp_bundle(OSP_Data_SQLite_Bundle "poco.data.sqlite"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/SQLiteBundleActivator.cpp
    LINK_LIBS Poco::OSP Poco::DataSQLite Poco::Data Poco::Util Poco::XML Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/SQLite.bndlspec
)
