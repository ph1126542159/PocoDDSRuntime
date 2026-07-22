include(FetchContent)

function(pdr_require_googletest)
    find_package(GTest CONFIG QUIET PATHS "${PDR_INSTALL_PREFIX}" NO_DEFAULT_PATH)
    if(GTest_FOUND)
        return()
    endif()
    if(NOT PDR_BOOTSTRAP_DEPENDENCIES)
        message(FATAL_ERROR "GoogleTest not found; enable PDR_BOOTSTRAP_DEPENDENCIES")
    endif()
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    FetchContent_Declare(googletest
        GIT_REPOSITORY https://github.com/google/googletest.git
        GIT_TAG v1.17.0
        GIT_SHALLOW TRUE)
    FetchContent_MakeAvailable(googletest)
endfunction()

function(pdr_require_fastdds)
    find_package(fastdds 3 CONFIG QUIET PATHS "${PDR_INSTALL_PREFIX}")
    if(fastdds_FOUND)
        return()
    endif()
    message(FATAL_ERROR
        "Fast-DDS was requested but is not installed. Run cmake/bootstrap-dependencies.cmake "
        "to build Fast-CDR, foonathan_memory_vendor and Fast-DDS into build/install.")
endfunction()

function(pdr_require_opentelemetry)
    find_package(opentelemetry-cpp CONFIG QUIET PATHS "${PDR_INSTALL_PREFIX}")
    if(opentelemetry-cpp_FOUND)
        return()
    endif()
    message(FATAL_ERROR
        "OpenTelemetry was requested but is not installed. Run cmake/bootstrap-dependencies.cmake.")
endfunction()

function(pdr_require_poco)
    find_package(Poco 1.15.3 CONFIG QUIET COMPONENTS Foundation Util JSON
        PATHS "${PDR_INSTALL_PREFIX}")
    if(Poco_FOUND)
        return()
    endif()
    message(FATAL_ERROR
        "Poco 1.15.3 was requested but is not installed. Run the dependency superbuild in cmake/. "
        "The project never vendors the upstream Poco source tree.")
endfunction()
