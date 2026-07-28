function(pdr_configure_main_process target)
    set(process_dir "${CMAKE_BINARY_DIR}/bin")
    set_target_properties(${target} PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${process_dir}")
    if(CMAKE_CONFIGURATION_TYPES)
        foreach(configuration IN LISTS CMAKE_CONFIGURATION_TYPES)
            string(TOUPPER "${configuration}" configuration_upper)
            set_target_properties(${target} PROPERTIES
                RUNTIME_OUTPUT_DIRECTORY_${configuration_upper} "${process_dir}")
        endforeach()
    endif()

    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory
            "$<TARGET_FILE_DIR:${target}>/logs"
            "$<TARGET_FILE_DIR:${target}>/bundles"
        VERBATIM)
endfunction()

function(pdr_configure_subprocess target)
    set(process_dir "${CMAKE_BINARY_DIR}/bin/processes/${target}")
    set_target_properties(${target} PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${process_dir}")
    if(CMAKE_CONFIGURATION_TYPES)
        foreach(configuration IN LISTS CMAKE_CONFIGURATION_TYPES)
            string(TOUPPER "${configuration}" configuration_upper)
            set_target_properties(${target} PROPERTIES
                RUNTIME_OUTPUT_DIRECTORY_${configuration_upper} "${process_dir}")
        endforeach()
    endif()

    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory
            "$<TARGET_FILE_DIR:${target}>/logs"
            "$<TARGET_FILE_DIR:${target}>/bundles"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_RUNTIME_DLLS:${target}>
            "$<TARGET_FILE_DIR:${target}>"
        COMMAND_EXPAND_LISTS
        VERBATIM)

    # OpenSSL is discovered through FindOpenSSL and its imported targets do not
    # expose the Windows runtime DLLs to TARGET_RUNTIME_DLLS.  Copy those DLLs
    # explicitly so subprocess executables are independently launchable.
    if(WIN32 AND OPENSSL_INCLUDE_DIR)
        get_filename_component(openssl_root "${OPENSSL_INCLUDE_DIR}" DIRECTORY)
        file(GLOB openssl_runtime_dlls
            "${openssl_root}/bin/libcrypto*.dll"
            "${openssl_root}/bin/libssl*.dll")
        foreach(openssl_runtime_dll IN LISTS openssl_runtime_dlls)
            add_custom_command(TARGET ${target} POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    "${openssl_runtime_dll}"
                    "$<TARGET_FILE_DIR:${target}>"
                VERBATIM)
        endforeach()
    endif()
endfunction()

function(pdr_configure_test_output_tree directory)
    get_property(directory_targets DIRECTORY "${directory}"
        PROPERTY BUILDSYSTEM_TARGETS)
    foreach(target IN LISTS directory_targets)
        get_target_property(target_type "${target}" TYPE)
        if(target_type STREQUAL "EXECUTABLE" AND
           target MATCHES "(-smoke|-test|-probe)$")
            set_target_properties("${target}" PROPERTIES
                RUNTIME_OUTPUT_DIRECTORY "${PDR_TEST_OUTPUT_DIRECTORY}"
                FOLDER "Tests")
            if(CMAKE_CONFIGURATION_TYPES)
                foreach(configuration IN LISTS CMAKE_CONFIGURATION_TYPES)
                    string(TOUPPER "${configuration}" configuration_upper)
                    set_target_properties("${target}" PROPERTIES
                        RUNTIME_OUTPUT_DIRECTORY_${configuration_upper}
                            "${PDR_TEST_OUTPUT_DIRECTORY}")
                endforeach()
            endif()
        endif()
    endforeach()

    get_property(child_directories DIRECTORY "${directory}"
        PROPERTY SUBDIRECTORIES)
    foreach(child_directory IN LISTS child_directories)
        pdr_configure_test_output_tree("${child_directory}")
    endforeach()
endfunction()
