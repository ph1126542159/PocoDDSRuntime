cmake_minimum_required(VERSION 3.24)
include(ExternalProject)

if(NOT DEFINED PDR_SOURCE_DIR)
    get_filename_component(PDR_SOURCE_DIR "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
endif()
if(NOT DEFINED PDR_BINARY_DIR)
    set(PDR_BINARY_DIR "${PDR_SOURCE_DIR}/build")
endif()
set(prefix "${PDR_BINARY_DIR}/install")
set(common -DCMAKE_INSTALL_PREFIX=${prefix} -DCMAKE_PREFIX_PATH=${prefix}
    -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON)

find_package(Poco 1.15.3 CONFIG QUIET COMPONENTS Foundation Util JSON)
if(NOT Poco_FOUND)
    ExternalProject_Add(poco
        GIT_REPOSITORY https://github.com/pocoproject/poco.git
        GIT_TAG poco-1.15.3-release GIT_SHALLOW TRUE
        CMAKE_ARGS ${common} -DENABLE_TESTS=OFF -DENABLE_SAMPLES=OFF
            -DENABLE_PAGECOMPILER=OFF -DENABLE_PAGECOMPILER_FILE2PAGE=OFF
            -DENABLE_DATA_POSTGRESQL=OFF -DENABLE_DATA_MYSQL=OFF
            -DENABLE_MONGODB=OFF -DENABLE_REDIS=OFF)
else()
    message(STATUS "Using existing Poco ${Poco_VERSION}")
endif()

ExternalProject_Add(foonathan_memory
    GIT_REPOSITORY https://github.com/eProsima/foonathan_memory_vendor.git
    GIT_TAG v1.4.1 GIT_SHALLOW TRUE
    CMAKE_ARGS ${common} -DFOONATHAN_MEMORY_BUILD_EXAMPLES=OFF)
ExternalProject_Add(fastcdr
    GIT_REPOSITORY https://github.com/eProsima/Fast-CDR.git
    GIT_TAG v2.3.6 GIT_SHALLOW TRUE
    CMAKE_ARGS ${common} -DBUILD_TESTING=OFF)
ExternalProject_Add(fastdds
    GIT_REPOSITORY https://github.com/eProsima/Fast-DDS.git
    GIT_TAG v3.6.2 GIT_SHALLOW TRUE
    DEPENDS foonathan_memory fastcdr
    CMAKE_ARGS ${common} -DCOMPILE_EXAMPLES=OFF -DBUILD_TESTING=OFF
        -DTHIRDPARTY=ON -DTHIRDPARTY_Asio=ON -DTHIRDPARTY_TinyXML2=ON
        -DTHIRDPARTY_UPDATE=OFF)
ExternalProject_Add(opentelemetry
    GIT_REPOSITORY https://github.com/open-telemetry/opentelemetry-cpp.git
    GIT_TAG v1.28.0 GIT_SHALLOW TRUE
    GIT_SUBMODULES ""
    CMAKE_ARGS ${common} -DBUILD_TESTING=OFF -DWITH_OTLP_GRPC=OFF
        -DWITH_OTLP_HTTP=OFF -DWITH_OTLP_FILE=OFF -DWITH_EXAMPLES=OFF
        -DWITH_ELASTICSEARCH=OFF -DWITH_ZIPKIN=OFF -DWITH_ETW=OFF
        -DWITH_CONFIGURATION=OFF -DBUILD_W3CTRACECONTEXT_TEST=OFF)
ExternalProject_Add(googletest_install
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.17.0 GIT_SHALLOW TRUE
    CMAKE_ARGS ${common} -DINSTALL_GTEST=ON -Dgtest_force_shared_crt=ON)
