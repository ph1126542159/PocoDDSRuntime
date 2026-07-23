find_package(GTest 1.17.0 CONFIG QUIET)
if(GTest_FOUND)
    message(STATUS "Using existing GoogleTest ${GTest_VERSION}")
    return()
endif()

ExternalProject_Add(googletest_install
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.17.0 GIT_SHALLOW TRUE
    CMAKE_ARGS ${PDR_DEPENDENCY_CMAKE_ARGS}
        -DINSTALL_GTEST=ON -Dgtest_force_shared_crt=ON)
