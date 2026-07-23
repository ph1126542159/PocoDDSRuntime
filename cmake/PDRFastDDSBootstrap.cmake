set(fastdds_dependencies)

set(PDR_FOONATHAN_MEMORY_SOURCE_DIR "" CACHE PATH
    "Optional pre-populated foonathan_memory_vendor source directory")
set(PDR_FASTCDR_SOURCE_DIR "" CACHE PATH
    "Optional pre-populated Fast-CDR source directory")
set(PDR_FASTDDS_SOURCE_DIR "" CACHE PATH
    "Optional pre-populated Fast-DDS source directory")

find_package(foonathan_memory CONFIG QUIET)
if(foonathan_memory_FOUND)
    message(STATUS "Using existing foonathan_memory")
else()
    set(_foonathan_source_args
        GIT_REPOSITORY https://github.com/eProsima/foonathan_memory_vendor.git
        GIT_TAG v1.4.1 GIT_SHALLOW TRUE)
    if(PDR_FOONATHAN_MEMORY_SOURCE_DIR)
        set(_foonathan_source_args
            SOURCE_DIR "${PDR_FOONATHAN_MEMORY_SOURCE_DIR}"
            DOWNLOAD_COMMAND "")
    endif()
    ExternalProject_Add(foonathan_memory
        ${_foonathan_source_args}
        CMAKE_ARGS ${PDR_DEPENDENCY_CMAKE_ARGS}
            -DFOONATHAN_MEMORY_BUILD_EXAMPLES=OFF)
    unset(_foonathan_source_args)
    list(APPEND fastdds_dependencies foonathan_memory)
endif()

find_package(fastcdr 2.3.6 CONFIG QUIET)
if(fastcdr_FOUND)
    message(STATUS "Using existing Fast-CDR ${fastcdr_VERSION}")
else()
    set(_fastcdr_source_args
        GIT_REPOSITORY https://github.com/eProsima/Fast-CDR.git
        GIT_TAG v2.3.6 GIT_SHALLOW TRUE)
    if(PDR_FASTCDR_SOURCE_DIR)
        set(_fastcdr_source_args
            SOURCE_DIR "${PDR_FASTCDR_SOURCE_DIR}"
            DOWNLOAD_COMMAND "")
    endif()
    ExternalProject_Add(fastcdr
        ${_fastcdr_source_args}
        CMAKE_ARGS ${PDR_DEPENDENCY_CMAKE_ARGS} -DBUILD_TESTING=OFF)
    unset(_fastcdr_source_args)
    list(APPEND fastdds_dependencies fastcdr)
endif()

find_package(fastdds 3.6.2 CONFIG QUIET)
if(fastdds_FOUND)
    message(STATUS "Using existing Fast-DDS ${fastdds_VERSION}")
else()
    set(_fastdds_source_args
        GIT_REPOSITORY https://github.com/eProsima/Fast-DDS.git
        GIT_TAG v3.6.2 GIT_SHALLOW TRUE)
    if(PDR_FASTDDS_SOURCE_DIR)
        set(_fastdds_source_args
            SOURCE_DIR "${PDR_FASTDDS_SOURCE_DIR}"
            DOWNLOAD_COMMAND "")
    endif()
    ExternalProject_Add(fastdds
        ${_fastdds_source_args}
        DEPENDS ${fastdds_dependencies}
        CMAKE_ARGS ${PDR_DEPENDENCY_CMAKE_ARGS}
            -DCOMPILE_EXAMPLES=OFF -DBUILD_TESTING=OFF
            -DTHIRDPARTY=ON -DTHIRDPARTY_Asio=ON -DTHIRDPARTY_TinyXML2=ON
            -DTHIRDPARTY_UPDATE=OFF)
    unset(_fastdds_source_args)
endif()
