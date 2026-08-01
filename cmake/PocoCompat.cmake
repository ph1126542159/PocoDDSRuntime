macro(_POCO_IS_WINDOWS_COMPATIBLE input_path out_var)
    get_filename_component(_poco_name "${input_path}" NAME)
    get_filename_component(_poco_dir "${input_path}" DIRECTORY)
    set(${out_var} TRUE)

    if(_poco_name STREQUAL "SyslogChannel.cpp")
        set(${out_var} FALSE)
    endif()

    if(_poco_name MATCHES "^(.*)_(WIN32U|WIN32|WINCE|UNIX|POSIX|VX|Android|ANDROID|QNX|SUN|DEC|HPUX|DUMMY|STD|C99)\\.(c|cc|cpp|cxx)$")
        set(_poco_base "${CMAKE_MATCH_1}.cpp")
        set(_poco_suffix "${CMAKE_MATCH_2}")
        if(EXISTS "${_poco_dir}/${_poco_base}")
            set(${out_var} FALSE)
        elseif(_poco_suffix MATCHES "^(WIN32U|WIN32|STD|C99)$")
            set(${out_var} TRUE)
        else()
            set(${out_var} FALSE)
        endif()
    endif()
endmacro()

macro(_POCO_APPEND_SOURCES out_var)
    foreach(_poco_item ${ARGN})
        set(_poco_keep TRUE)
        _POCO_IS_WINDOWS_COMPATIBLE("${_poco_item}" _poco_keep)
        if(_poco_keep)
            list(APPEND ${out_var} "${_poco_item}")
        endif()
    endforeach()
endmacro()

macro(POCO_SOURCES_AUTO out_var)
    _POCO_APPEND_SOURCES(${out_var} ${ARGN})
endmacro()

macro(POCO_HEADERS_AUTO out_var)
    _POCO_APPEND_SOURCES(${out_var} ${ARGN})
endmacro()

macro(POCO_SOURCES out_var)
    set(_poco_items ${ARGN})
    list(LENGTH _poco_items _poco_len)
    if(_poco_len GREATER 0)
        list(REMOVE_AT _poco_items 0)
    endif()
    _POCO_APPEND_SOURCES(${out_var} ${_poco_items})
endmacro()

macro(POCO_HEADERS out_var)
    set(_poco_items ${ARGN})
    list(LENGTH _poco_items _poco_len)
    if(_poco_len GREATER 0)
        list(REMOVE_AT _poco_items 0)
    endif()
    _POCO_APPEND_SOURCES(${out_var} ${_poco_items})
endmacro()

macro(POCO_SOURCES_AUTO_PLAT out_var platform)
    if("${platform}" STREQUAL "WIN32")
        if(WIN32)
            _POCO_APPEND_SOURCES(${out_var} ${ARGN})
        endif()
    elseif("${platform}" STREQUAL "WINCE")
        if(WINCE)
            _POCO_APPEND_SOURCES(${out_var} ${ARGN})
        endif()
    elseif("${platform}" STREQUAL "UNIX")
        if(UNIX)
            _POCO_APPEND_SOURCES(${out_var} ${ARGN})
        endif()
    endif()
endmacro()

macro(POCO_MESSAGES out_var)
endmacro()

macro(POCO_INSTALL)
    if(ARGC GREATER 0 AND TARGET ${ARGV0})
        install(TARGETS ${ARGV0}
            RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
            LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
            ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        )
    endif()
endmacro()

macro(POCO_GENERATE_PACKAGE)
endmacro()

if(NOT TARGET Poco::CppUnit)
    find_library(PDR_CPPUNIT_LIBRARY_RELEASE
        NAMES CppUnitmd CppUnit
        PATHS "${PDR_INSTALL_PREFIX}/lib"
        NO_DEFAULT_PATH)
    find_library(PDR_CPPUNIT_LIBRARY_DEBUG
        NAMES CppUnitmdd CppUnitd
        PATHS "${PDR_INSTALL_PREFIX}/lib"
        NO_DEFAULT_PATH)
    if(PDR_CPPUNIT_LIBRARY_RELEASE)
        add_library(Poco::CppUnit UNKNOWN IMPORTED)
        set_target_properties(Poco::CppUnit PROPERTIES
            IMPORTED_LOCATION "${PDR_CPPUNIT_LIBRARY_RELEASE}"
            IMPORTED_LOCATION_RELEASE "${PDR_CPPUNIT_LIBRARY_RELEASE}"
            IMPORTED_LOCATION_RELWITHDEBINFO "${PDR_CPPUNIT_LIBRARY_RELEASE}"
            IMPORTED_LOCATION_MINSIZEREL "${PDR_CPPUNIT_LIBRARY_RELEASE}"
            INTERFACE_INCLUDE_DIRECTORIES "${PDR_INSTALL_PREFIX}/include"
            INTERFACE_LINK_LIBRARIES Poco::Foundation)
        if(PDR_CPPUNIT_LIBRARY_DEBUG)
            set_target_properties(Poco::CppUnit PROPERTIES
                IMPORTED_LOCATION_DEBUG "${PDR_CPPUNIT_LIBRARY_DEBUG}")
        endif()
    endif()
endif()

function(myiot_copy_windows_runtime_dlls target_name)
    if(NOT WIN32 OR NOT TARGET ${target_name})
        return()
    endif()

    # Several tools share the same output directory.  Giving every tool an
    # identical POST_BUILD copy step makes parallel MSBuild invocations race
    # while replacing the same DLLs.  A single shared target serializes that
    # work and remains a prerequisite of every consumer.
    if(NOT TARGET myiot_windows_runtime_dlls)
        add_custom_target(myiot_windows_runtime_dlls)
        add_custom_command(TARGET myiot_windows_runtime_dlls POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E make_directory
                "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
            VERBATIM)
        file(GLOB runtime_dlls "${PDR_INSTALL_PREFIX}/bin/*.dll")
        if(OPENSSL_INCLUDE_DIR)
            get_filename_component(openssl_root "${OPENSSL_INCLUDE_DIR}" DIRECTORY)
            file(GLOB openssl_runtime_dlls
                "${openssl_root}/bin/libcrypto*.dll"
                "${openssl_root}/bin/libssl*.dll")
            list(APPEND runtime_dlls ${openssl_runtime_dlls})
        endif()
        list(REMOVE_DUPLICATES runtime_dlls)
        foreach(runtime_dll IN LISTS runtime_dlls)
            add_custom_command(TARGET myiot_windows_runtime_dlls POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    "${runtime_dll}"
                    "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
                VERBATIM)
        endforeach()
    endif()
    add_dependencies(${target_name} myiot_windows_runtime_dlls)
endfunction()
