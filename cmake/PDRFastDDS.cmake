include_guard(GLOBAL)

function(pdr_require_fastdds)
    find_package(fastdds 3 CONFIG QUIET PATHS "${PDR_INSTALL_PREFIX}")
    if(fastdds_FOUND)
        return()
    endif()
    message(FATAL_ERROR
        "Fast-DDS was requested but is not installed. Configure and build cmake/ in "
        "build/dependencies to install Fast-CDR, foonathan_memory_vendor and Fast-DDS.")
endfunction()
