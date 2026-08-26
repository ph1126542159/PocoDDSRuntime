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

# Declare a stable, independently buildable delivery boundary without merging
# the member libraries or Bundles into a new binary.  The group remains a
# normal CMake target, so local builds and CI use the same dependency graph.
function(pdr_add_component_group_target target)
    set(options)
    set(one_value_args COMPONENT FOLDER)
    set(multi_value_args DEPENDS)
    cmake_parse_arguments(PDR_GROUP
        "${options}" "${one_value_args}" "${multi_value_args}" ${ARGN})

    if(NOT target OR TARGET "${target}")
        message(FATAL_ERROR
            "Component group target is empty or already exists: ${target}")
    endif()
    if(NOT PDR_GROUP_COMPONENT MATCHES "^[a-z0-9][a-z0-9-]*$")
        message(FATAL_ERROR
            "Component group ${target} has an invalid component id")
    endif()
    if(NOT PDR_GROUP_DEPENDS)
        message(FATAL_ERROR "Component group ${target} has no member targets")
    endif()

    set(unique_members ${PDR_GROUP_DEPENDS})
    list(REMOVE_DUPLICATES unique_members)
    list(LENGTH PDR_GROUP_DEPENDS member_count)
    list(LENGTH unique_members unique_member_count)
    if(NOT member_count EQUAL unique_member_count)
        message(FATAL_ERROR "Component group ${target} has duplicate members")
    endif()
    foreach(member IN LISTS unique_members)
        if(NOT TARGET "${member}")
            message(FATAL_ERROR
                "Component group ${target} references unknown target ${member}")
        endif()
    endforeach()
    list(SORT unique_members)

    add_custom_target(${target})
    add_dependencies(${target} ${unique_members})
    if(PDR_GROUP_FOLDER)
        set_target_properties(${target} PROPERTIES FOLDER "${PDR_GROUP_FOLDER}")
    endif()
    set_property(TARGET ${target} PROPERTY
        PDR_COMPONENT_GROUP_COMPONENT "${PDR_GROUP_COMPONENT}")
    set_property(TARGET ${target} PROPERTY
        PDR_COMPONENT_GROUP_MEMBERS "${unique_members}")
    set_property(GLOBAL APPEND PROPERTY PDR_COMPONENT_GROUP_TARGETS "${target}")
endfunction()

function(_pdr_component_json_escape value output)
    set(escaped "${value}")
    string(REPLACE "\\" "\\\\" escaped "${escaped}")
    string(REPLACE "\"" "\\\"" escaped "${escaped}")
    set(${output} "${escaped}" PARENT_SCOPE)
endfunction()

# Export the configured group membership as machine-readable evidence.  The
# validator combines this with the complete CMake link manifest, avoiding a
# second hand-maintained list of production targets.
function(pdr_write_component_group_manifest output_file)
    get_property(groups GLOBAL PROPERTY PDR_COMPONENT_GROUP_TARGETS)
    if(NOT groups)
        message(FATAL_ERROR "No component build groups were declared")
    endif()
    list(REMOVE_DUPLICATES groups)
    list(SORT groups)

    get_filename_component(output_directory "${output_file}" DIRECTORY)
    file(MAKE_DIRECTORY "${output_directory}")
    _pdr_component_json_escape("${PDR_PROFILE}" escaped_profile)
    file(WRITE "${output_file}"
        "{\n  \"schemaVersion\": 1,\n"
        "  \"operation\": \"framework-component-build-groups\",\n"
        "  \"profile\": \"${escaped_profile}\",\n"
        "  \"groups\": [\n")

    set(first_group TRUE)
    foreach(group IN LISTS groups)
        get_target_property(component "${group}" PDR_COMPONENT_GROUP_COMPONENT)
        get_target_property(members "${group}" PDR_COMPONENT_GROUP_MEMBERS)
        if(NOT component OR NOT members)
            message(FATAL_ERROR
                "Component group ${group} lacks component or member metadata")
        endif()
        list(REMOVE_DUPLICATES members)
        list(SORT members)
        _pdr_component_json_escape("${group}" escaped_group)
        _pdr_component_json_escape("${component}" escaped_component)
        if(first_group)
            set(first_group FALSE)
        else()
            file(APPEND "${output_file}" ",\n")
        endif()
        file(APPEND "${output_file}"
            "    {\"component\": \"${escaped_component}\", "
            "\"target\": \"${escaped_group}\", \"members\": [")
        set(first_member TRUE)
        foreach(member IN LISTS members)
            _pdr_component_json_escape("${member}" escaped_member)
            if(first_member)
                set(first_member FALSE)
            else()
                file(APPEND "${output_file}" ", ")
            endif()
            file(APPEND "${output_file}" "\"${escaped_member}\"")
        endforeach()
        file(APPEND "${output_file}" "]}")
    endforeach()
    file(APPEND "${output_file}" "\n  ]\n}\n")
endfunction()
