include_guard(GLOBAL)
include(CMakeParseArguments)

function(pdr_add_osp_bundle target_name)
    set(options)
    set(oneValueArgs SYMBOLIC_NAME BUNDLE_SPEC OUTPUT_DIRECTORY)
    set(multiValueArgs SOURCES LINK_LIBS INCLUDE_DIRS)
    cmake_parse_arguments(PDR_PLUGIN "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})
    if(NOT PDR_PLUGIN_SYMBOLIC_NAME OR NOT PDR_PLUGIN_BUNDLE_SPEC OR NOT PDR_PLUGIN_SOURCES)
        message(FATAL_ERROR "pdr_add_osp_bundle requires SYMBOLIC_NAME, BUNDLE_SPEC and SOURCES")
    endif()
    if(NOT TARGET PocoDDS::Plugins OR NOT TARGET PocoDDS::BundleCreator)
        message(FATAL_ERROR "PocoDDSRuntime Plugins component is not available")
    endif()
    string(REGEX MATCH "^[0-9]+" _pdr_consumer_compiler_major "${CMAKE_CXX_COMPILER_VERSION}")
    if(NOT CMAKE_CXX_COMPILER_ID STREQUAL PocoDDSRuntime_PLUGIN_COMPILER_ID OR
       NOT _pdr_consumer_compiler_major STREQUAL PocoDDSRuntime_PLUGIN_COMPILER_MAJOR)
        message(FATAL_ERROR
            "Plugin compiler ABI does not match PocoDDSRuntime: got "
            "${CMAKE_CXX_COMPILER_ID}-${_pdr_consumer_compiler_major}, expected "
            "${PocoDDSRuntime_PLUGIN_COMPILER_ID}-${PocoDDSRuntime_PLUGIN_COMPILER_MAJOR}")
    endif()
    add_library(${target_name} SHARED ${PDR_PLUGIN_SOURCES})
    set_target_properties(${target_name} PROPERTIES
        OUTPUT_NAME "${PDR_PLUGIN_SYMBOLIC_NAME}" PREFIX "" DEBUG_POSTFIX "")
    target_link_libraries(${target_name} PRIVATE PocoDDS::Plugins ${PDR_PLUGIN_LINK_LIBS})
    if(UNIX AND NOT APPLE)
        target_link_options(${target_name} PRIVATE
            "LINKER:--exclude-libs,ALL"
            "LINKER:-Bsymbolic")
    endif()
    if(PDR_PLUGIN_INCLUDE_DIRS)
        target_include_directories(${target_name} PRIVATE ${PDR_PLUGIN_INCLUDE_DIRS})
    endif()
    get_filename_component(_pdr_spec "${PDR_PLUGIN_BUNDLE_SPEC}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    set(_pdr_output "${PDR_PLUGIN_OUTPUT_DIRECTORY}")
    if(NOT _pdr_output)
        set(_pdr_output "${CMAKE_BINARY_DIR}/bundles")
    endif()
    if(WIN32)
        set(_pdr_option_prefix "/")
        set(_pdr_os_name "Windows_NT")
    else()
        set(_pdr_option_prefix "--")
        set(_pdr_os_name "${CMAKE_SYSTEM_NAME}")
    endif()
    if(CMAKE_VS_PLATFORM_NAME STREQUAL "x64")
        set(_pdr_os_arch "AMD64")
    elseif(CMAKE_SYSTEM_PROCESSOR)
        set(_pdr_os_arch "${CMAKE_SYSTEM_PROCESSOR}")
    else()
        set(_pdr_os_arch "unknown")
    endif()
    file(GLOB_RECURSE _pdr_resources CONFIGURE_DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/bundle/*")
    set(_pdr_stamp "${CMAKE_CURRENT_BINARY_DIR}/${target_name}.bndl.stamp")
    if(CMAKE_CROSSCOMPILING AND NOT PDR_BUNDLE_CREATOR_COMMAND)
        message(FATAL_ERROR
            "Cross-compiling an OSP bundle requires PDR_BUNDLE_CREATOR_COMMAND "
            "to name a host-runnable PocoDDS BundleCreator command")
    endif()
    if(PDR_BUNDLE_CREATOR_COMMAND)
        set(_pdr_bundle_creator ${PDR_BUNDLE_CREATOR_COMMAND})
        set(_pdr_bundle_creator_dependency)
    else()
        set(_pdr_bundle_creator "$<TARGET_FILE:PocoDDS::BundleCreator>")
        set(_pdr_bundle_creator_dependency PocoDDS::BundleCreator)
    endif()
    add_custom_command(
        OUTPUT "${_pdr_stamp}"
        COMMAND ${CMAKE_COMMAND} -E make_directory "${_pdr_output}"
        COMMAND ${_pdr_bundle_creator}
            "${_pdr_option_prefix}output-dir=${_pdr_output}"
            "${_pdr_option_prefix}osname=${_pdr_os_name}"
            "${_pdr_option_prefix}osarch=${_pdr_os_arch}"
            "${_pdr_option_prefix}code=$<TARGET_FILE:${target_name}>"
            "${_pdr_option_prefix}define=pdrPluginApi=${PocoDDSRuntime_PLUGIN_API_VERSION}"
            "${_pdr_option_prefix}define=pdrPluginAbi=${PocoDDSRuntime_PLUGIN_ABI_VERSION}"
            "${_pdr_option_prefix}define=pdrPluginAbiFingerprint=${PocoDDSRuntime_PLUGIN_ABI_FINGERPRINT}"
            "${_pdr_option_prefix}define=pdrRuntimeRange=${PocoDDSRuntime_PLUGIN_RUNTIME_RANGE}"
            "${_pdr_spec}"
        COMMAND ${CMAKE_COMMAND} -E touch "${_pdr_stamp}"
        DEPENDS ${target_name} ${_pdr_bundle_creator_dependency} "${_pdr_spec}" ${_pdr_resources}
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
        VERBATIM)
    add_custom_target(${target_name}_Package ALL DEPENDS "${_pdr_stamp}")
    set(${target_name}_BUNDLE_DIRECTORY "${_pdr_output}" PARENT_SCOPE)
endfunction()
