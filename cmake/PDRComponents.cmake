include_guard(GLOBAL)
include(CMakeParseArguments)

# Discover direct child components with their own CMakeLists.txt.  Keeping the
# discovery rule here means a new service, subprocess or page Bundle does not
# require another edit to a central registry.
function(pdr_add_component_directories root)
    set(options)
    set(one_value_args FOLDER)
    set(multi_value_args EXCLUDE)
    cmake_parse_arguments(PDR_COMPONENT
        "${options}" "${one_value_args}" "${multi_value_args}" ${ARGN})

    get_filename_component(component_root "${root}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    if(NOT IS_DIRECTORY "${component_root}")
        message(FATAL_ERROR "Component root does not exist: ${component_root}")
    endif()

    file(GLOB component_candidates CONFIGURE_DEPENDS
        LIST_DIRECTORIES true "${component_root}/*")
    list(SORT component_candidates)

    foreach(component_dir IN LISTS component_candidates)
        if(NOT IS_DIRECTORY "${component_dir}" OR
           NOT EXISTS "${component_dir}/CMakeLists.txt")
            continue()
        endif()

        get_filename_component(component_name "${component_dir}" NAME)
        if(component_name IN_LIST PDR_COMPONENT_EXCLUDE)
            message(STATUS "PocoDDSRuntime component disabled: ${component_name}")
            continue()
        endif()

        set(previous_cmake_folder "${CMAKE_FOLDER}")
        if(PDR_COMPONENT_FOLDER)
            set(CMAKE_FOLDER "${PDR_COMPONENT_FOLDER}/${component_name}")
        endif()
        add_subdirectory("${component_dir}" "${component_name}")
        set(CMAKE_FOLDER "${previous_cmake_folder}")
    endforeach()
endfunction()
