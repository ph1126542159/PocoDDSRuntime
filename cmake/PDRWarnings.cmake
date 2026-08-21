function(pdr_set_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive- /EHsc)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
    endif()
endfunction()

function(pdr_isolate_embedded_static_dependencies target)
    if(NOT UNIX OR APPLE)
        return()
    endif()

    get_target_property(target_type ${target} TYPE)
    # Third-party packages are PIC static archives.  Prevent their globals from
    # entering the process-wide ELF namespace, and bind definitions compiled
    # into PDR shared objects locally.  Without both controls, an executable,
    # shared platform library and dynamically loaded OSP bundle can resolve one
    # inline/static-library singleton to the same storage and register multiple
    # atexit destructors for it.
    target_link_options(${target} PRIVATE "LINKER:--exclude-libs,ALL")
    if(target_type STREQUAL "SHARED_LIBRARY" OR target_type STREQUAL "MODULE_LIBRARY")
        target_link_options(${target} PRIVATE "LINKER:-Bsymbolic")
    endif()
endfunction()
