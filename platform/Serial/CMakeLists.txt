# Sources
file(GLOB SRCS_G "src/*.cpp")
POCO_SOURCES_AUTO(SRCS ${SRCS_G})

# Headers
file(GLOB_RECURSE HDRS_G "include/*.h")
POCO_HEADERS_AUTO(SRCS ${HDRS_G})

add_library(Serial ${SRCS})
add_library(Poco::Serial ALIAS Serial)
set_target_properties(Serial
    PROPERTIES
    VERSION "1" SOVERSION "1"
    OUTPUT_NAME PocoSerial
    DEFINE_SYMBOL Serial_EXPORTS
)

target_link_libraries(Serial PUBLIC Poco::Foundation)
target_include_directories(Serial
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)

POCO_INSTALL(Serial)
POCO_GENERATE_PACKAGE(Serial)
