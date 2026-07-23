add_executable(OSPBundleCreator
    ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleCreator.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/ManifestInfo.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/ManifestInfo.h
)

set_target_properties(OSPBundleCreator
    PROPERTIES
    OUTPUT_NAME bundle
)

myiot_copy_windows_runtime_dlls(OSPBundleCreator)

target_link_libraries(OSPBundleCreator
    PRIVATE
        Poco::OSP
        Poco::Zip
        Poco::Util
        Poco::JSON
        Poco::XML
        Poco::Foundation
)

target_include_directories(OSPBundleCreator
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_CURRENT_SOURCE_DIR}/../include
        ${CMAKE_CURRENT_SOURCE_DIR}/../src
)
