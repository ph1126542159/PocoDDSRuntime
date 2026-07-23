add_executable(OSPStripBundle
    ${CMAKE_CURRENT_SOURCE_DIR}/src/StripBundle.cpp
)

set_target_properties(OSPStripBundle
    PROPERTIES
    OUTPUT_NAME strip-bundle
)

myiot_copy_windows_runtime_dlls(OSPStripBundle)

target_link_libraries(OSPStripBundle
    PRIVATE
        Poco::Zip
        Poco::Util
        Poco::JSON
        Poco::XML
        Poco::Foundation
)
