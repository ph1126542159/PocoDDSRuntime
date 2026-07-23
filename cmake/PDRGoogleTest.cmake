include_guard(GLOBAL)
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
    set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
    FetchContent_Declare(googletest
        GIT_REPOSITORY https://github.com/google/googletest.git
        GIT_TAG v1.17.0
        GIT_SHALLOW TRUE)
    FetchContent_MakeAvailable(googletest)
endfunction()
