myiot_add_osp_bundle(OSP_Crypto_Bundle "poco.crypto"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/CryptoBundleActivator.cpp
    LINK_LIBS Poco::Crypto Poco::OSP Poco::Util Poco::XML Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/Crypto.bndlspec
)
