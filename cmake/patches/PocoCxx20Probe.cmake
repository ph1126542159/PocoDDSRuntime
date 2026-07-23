set(probe_file "${POCO_SOURCE_DIR}/cmake/CXX2x.cmake")
if(NOT EXISTS "${probe_file}")
    message(FATAL_ERROR "Poco C++20 probe not found: ${probe_file}")
endif()

file(READ "${probe_file}" contents)
set(marker "# PocoDDSRuntime: GCC before 10 has no C++20 dialect flag")
string(FIND "${contents}" "${marker}" marker_position)
if(NOT marker_position EQUAL -1)
    return()
endif()

set(needle "function(check_for_cxx20_compiler _VAR)\n")
set(replacement
"function(check_for_cxx20_compiler _VAR)
    ${marker}
    if(CMAKE_CXX_COMPILER_ID STREQUAL \"GNU\" AND
       CMAKE_CXX_COMPILER_VERSION VERSION_LESS 10.0)
        set(\${_VAR} PARENT_SCOPE)
        message(STATUS \"Checking for C++20 compiler - unavailable\")
        return()
    endif()
")
string(FIND "${contents}" "${needle}" position)
if(position EQUAL -1)
    message(FATAL_ERROR "Unexpected Poco CXX2x.cmake layout")
endif()
string(REPLACE "${needle}" "${replacement}" contents "${contents}")
file(WRITE "${probe_file}" "${contents}")
