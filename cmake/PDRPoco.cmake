include_guard(GLOBAL)

function(pdr_require_poco)
    find_package(Poco 1.15.3 CONFIG QUIET COMPONENTS
        Foundation XML JSON Util Net Crypto NetSSL Zip CppParser JWT Data DataSQLite
        PATHS "${PDR_INSTALL_PREFIX}")
    if(Poco_FOUND)
        return()
    endif()
    message(FATAL_ERROR
        "Poco 1.15.3 was requested but is not installed. Run the dependency superbuild in cmake/. "
        "The project never vendors the upstream Poco source tree.")
endfunction()
