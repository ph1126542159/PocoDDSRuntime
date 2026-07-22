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
    -DBUILD_SHARED_LIBS=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON)

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
    CMAKE_ARGS ${common} -DCOMPILE_EXAMPLES=OFF -DBUILD_TESTING=OFF)
ExternalProject_Add(opentelemetry
    GIT_REPOSITORY https://github.com/open-telemetry/opentelemetry-cpp.git
    GIT_TAG v1.28.0 GIT_SHALLOW TRUE
    CMAKE_ARGS ${common} -DBUILD_TESTING=OFF -DWITH_OTLP_GRPC=OFF
        -DWITH_OTLP_HTTP=ON -DWITH_EXAMPLES=OFF)
ExternalProject_Add(googletest_install
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.17.0 GIT_SHALLOW TRUE
    CMAKE_ARGS ${common} -DINSTALL_GTEST=ON -Dgtest_force_shared_crt=ON)
