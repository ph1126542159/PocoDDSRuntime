# Sources
file(GLOB SRCS_G "src/*.cpp")
POCO_SOURCES_AUTO(SRCS ${SRCS_G})

# Headers
file(GLOB_RECURSE HDRS_G "include/*.h")
POCO_HEADERS_AUTO(SRCS ${HDRS_G})

add_library(WebTunnel ${SRCS})
add_library(Poco::WebTunnel ALIAS WebTunnel)
set_target_properties(WebTunnel
    PROPERTIES
    VERSION "1" SOVERSION "1"
    OUTPUT_NAME PocoWebTunnel
    DEFINE_SYMBOL WebTunnel_EXPORTS
)

target_link_libraries(WebTunnel PUBLIC Poco::Net Poco::Foundation)
target_include_directories(WebTunnel
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)

POCO_INSTALL(WebTunnel)
POCO_GENERATE_PACKAGE(WebTunnel)
