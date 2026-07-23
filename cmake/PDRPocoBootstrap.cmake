find_package(Poco 1.15.3 CONFIG QUIET COMPONENTS
    Foundation XML JSON Util Net Crypto NetSSL Zip CppParser JWT)
if(Poco_FOUND)
    message(STATUS "Using existing Poco ${Poco_VERSION}")
    return()
endif()

set(PDR_POCO_ARCHIVE "" CACHE FILEPATH
    "Optional local Poco 1.15.3 source archive for offline builds")
set(_pdr_poco_url
    "https://github.com/pocoproject/poco/archive/refs/tags/poco-1.15.3-release.tar.gz")
if(PDR_POCO_ARCHIVE)
    if(NOT EXISTS "${PDR_POCO_ARCHIVE}")
        message(FATAL_ERROR "PDR_POCO_ARCHIVE does not exist: ${PDR_POCO_ARCHIVE}")
    endif()
    set(_pdr_poco_url "${PDR_POCO_ARCHIVE}")
endif()

ExternalProject_Add(poco
    URL "${_pdr_poco_url}"
    URL_HASH SHA256=4f112fea59e0c65f0fffe30a4957f8d66cf41528c21dd9903e6d7550022c794e
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    PATCH_COMMAND
        ${CMAKE_COMMAND}
        -DPOCO_SOURCE_DIR=<SOURCE_DIR>
        -P "${CMAKE_CURRENT_LIST_DIR}/patches/PocoCxx20Probe.cmake"
    CMAKE_ARGS ${PDR_DEPENDENCY_CMAKE_ARGS}
        -DENABLE_TESTS=OFF -DENABLE_SAMPLES=OFF
        -DENABLE_PAGECOMPILER=OFF -DENABLE_PAGECOMPILER_FILE2PAGE=OFF
        -DENABLE_CPPPARSER=ON -DENABLE_REDIS=ON
        -DENABLE_CPPUNIT=ON -DENABLE_INSTALL_CPPUNIT=ON
        -DENABLE_DATA_POSTGRESQL=OFF -DENABLE_DATA_MYSQL=OFF
        -DENABLE_MONGODB=OFF -DENABLE_REDIS=OFF)

unset(_pdr_poco_url)
