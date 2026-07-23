# Sources
set(SRCS)
file(GLOB SRCS_G "src/*.cpp")
POCO_SOURCES_AUTO(SRCS ${SRCS_G})

# Headers
set(HDRS_G)
file(GLOB_RECURSE HDRS_G "include/*.h")
POCO_HEADERS_AUTO(SRCS ${HDRS_G})

add_library(OSPUnit ${SRCS})
add_library(Poco::OSPUnit ALIAS OSPUnit)
set_target_properties(OSPUnit
    PROPERTIES
    VERSION "2" SOVERSION "2"
    OUTPUT_NAME PocoOSPUnit
    DEFINE_SYMBOL OSPUnit_EXPORTS
)

target_link_libraries(OSPUnit PUBLIC Poco::CppUnit Poco::OSP Poco::Foundation)
target_include_directories(OSPUnit
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_CURRENT_SOURCE_DIR}/../include
)
