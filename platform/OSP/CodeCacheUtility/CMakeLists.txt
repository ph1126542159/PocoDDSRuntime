add_executable(OSPCodeCacheUtility
    ${CMAKE_CURRENT_SOURCE_DIR}/src/CCUtility.cpp
)

set_target_properties(OSPCodeCacheUtility
    PROPERTIES
    OUTPUT_NAME ccutil
)

myiot_copy_windows_runtime_dlls(OSPCodeCacheUtility)

target_link_libraries(OSPCodeCacheUtility
    PRIVATE
        Poco::OSP
        Poco::Zip
        Poco::Util
        Poco::JSON
        Poco::XML
        Poco::Foundation
)

target_include_directories(OSPCodeCacheUtility
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/../include
        ${CMAKE_CURRENT_SOURCE_DIR}/../src
)
