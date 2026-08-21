# Web server, authentication and administration are supplied by the migrated
# platform/OSP Web bundles. This directory contains page bundles only.
function(pdr_add_webui_bundle target bundle_spec)
    get_filename_component(spec "${bundle_spec}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    if(ARGC GREATER 2 AND ARGV2 STREQUAL "GENERATED_RESOURCES")
        set(resources "${ARGV3}")
    else()
        file(GLOB_RECURSE resources CONFIGURE_DEPENDS
            "${CMAKE_CURRENT_SOURCE_DIR}/bundle/*")
    endif()
    set(stamp "${CMAKE_CURRENT_BINARY_DIR}/${target}.bndl.stamp")
    add_custom_command(
        OUTPUT "${stamp}"
        COMMAND ${CMAKE_COMMAND} -E make_directory "${PDR_BUNDLE_OUTPUT_DIRECTORY}"
        COMMAND ${MYIOT_OSP_BUNDLE_CREATOR_COMMAND}
            "${MYIOT_BUNDLE_OPT_PREFIX}output-dir=${PDR_BUNDLE_OUTPUT_DIRECTORY}"
            "${MYIOT_BUNDLE_OPT_PREFIX}osname=${MYIOT_OSP_BUNDLE_OSNAME}"
            "${MYIOT_BUNDLE_OPT_PREFIX}osarch=${MYIOT_OSP_BUNDLE_OSARCH}"
            "${spec}"
        COMMAND ${CMAKE_COMMAND} -E touch "${stamp}"
        DEPENDS OSPBundleCreator "${spec}" ${resources}
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
        VERBATIM)
    add_custom_target(${target}_Package ALL DEPENDS "${stamp}")
endfunction()

pdr_add_component_directories("${CMAKE_CURRENT_SOURCE_DIR}"
    FOLDER "WebUI")
