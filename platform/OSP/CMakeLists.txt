include(CMakeParseArguments)

if(WIN32)
    set(MYIOT_BUNDLE_OPT_PREFIX "/")
else()
    set(MYIOT_BUNDLE_OPT_PREFIX "--")
endif()

function(myiot_add_osp_bundle target_name output_name)
    set(options)
    set(oneValueArgs BUNDLE_SPEC)
    set(multiValueArgs SOURCES LINK_LIBS INCLUDE_DIRS)
    cmake_parse_arguments(BUNDLE "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

    add_library(${target_name} SHARED ${BUNDLE_SOURCES})
    set_target_properties(${target_name}
        PROPERTIES
        OUTPUT_NAME ${output_name}
        PREFIX ""
        DEBUG_POSTFIX d
    )
    target_link_libraries(${target_name} PRIVATE ${BUNDLE_LINK_LIBS})
    if(UNIX AND NOT APPLE)
        # Bundles contain static Poco/platform libraries. Bind their internal
        # symbols locally so ELF interposition does not merge independent
        # static objects with identical names across the executable and DSOs,
        # which otherwise causes duplicate atexit destruction on unload.
        target_link_options(${target_name} PRIVATE "-Wl,-Bsymbolic")
    endif()
    if(BUNDLE_INCLUDE_DIRS)
        target_include_directories(${target_name} PRIVATE ${BUNDLE_INCLUDE_DIRS})
    endif()

    if(BUNDLE_BUNDLE_SPEC)
        get_filename_component(bundle_spec "${BUNDLE_BUNDLE_SPEC}" ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        set(bundle_output_dir "${PDR_BUNDLE_OUTPUT_DIRECTORY}")
        set(bundle_stamp "${CMAKE_CURRENT_BINARY_DIR}/${target_name}.bndl.stamp")
        file(RELATIVE_PATH bundle_code_rel_dir "${CMAKE_CURRENT_SOURCE_DIR}" "${CMAKE_BINARY_DIR}/bin")
        if(MSVC)
            set(bundle_code_args "${MYIOT_BUNDLE_OPT_PREFIX}code=${bundle_code_rel_dir}/$<TARGET_FILE_NAME:${target_name}>")
        else()
            set(bundle_code_args "${MYIOT_BUNDLE_OPT_PREFIX}code=${bundle_code_rel_dir}/$<TARGET_FILE_NAME:${target_name}>*")
        endif()
        set(bundle_resource_deps)

        if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/bundle")
            file(GLOB_RECURSE bundle_resource_deps CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/bundle/*")
        endif()
        add_custom_command(
            OUTPUT "${bundle_stamp}"
            COMMAND ${CMAKE_COMMAND} -E make_directory "${bundle_output_dir}"
            COMMAND ${MYIOT_OSP_BUNDLE_CREATOR_COMMAND}
                "${MYIOT_BUNDLE_OPT_PREFIX}output-dir=${bundle_output_dir}"
                "${MYIOT_BUNDLE_OPT_PREFIX}osname=${MYIOT_OSP_BUNDLE_OSNAME}"
                "${MYIOT_BUNDLE_OPT_PREFIX}osarch=${MYIOT_OSP_BUNDLE_OSARCH}"
                ${bundle_code_args}
                "${bundle_spec}"
            COMMAND ${CMAKE_COMMAND} -E touch "${bundle_stamp}"
            DEPENDS
                OSPBundleCreator
                ${target_name}
                "$<TARGET_FILE:OSPBundleCreator>"
                "$<TARGET_FILE:${target_name}>"
                "${bundle_spec}"
                ${bundle_resource_deps}
            WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
            COMMAND_EXPAND_LISTS
            VERBATIM
        )

        add_custom_target(${target_name}_Package ALL DEPENDS "${bundle_stamp}")
        add_dependencies(${target_name}_Package ${target_name})
    endif()
endfunction()

# Sources
file(GLOB SRCS_G "src/*.cpp")
POCO_SOURCES_AUTO(SRCS ${SRCS_G})

# Headers
file(GLOB_RECURSE HDRS_G "include/*.h")
POCO_HEADERS_AUTO(SRCS ${HDRS_G})

add_library(OSP ${SRCS})
add_library(Poco::OSP ALIAS OSP)
set_target_properties(OSP
    PROPERTIES
    VERSION "2" SOVERSION "2"
    OUTPUT_NAME PocoOSP
    DEFINE_SYMBOL OSP_EXPORTS
)

target_link_libraries(OSP PUBLIC Poco::Zip Poco::Util Poco::XML Poco::Foundation)
target_include_directories(OSP
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)

set(MYIOT_OSP_BUNDLE_INCLUDE_DIRS
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

set(MYIOT_OSP_BUNDLE_OSNAME "${MYIOT_PLATFORM_OSNAME}")
set(MYIOT_OSP_BUNDLE_OSARCH "${MYIOT_PLATFORM_OSARCH}")

add_subdirectory(BundleCreator)
add_subdirectory(CodeCacheUtility)
add_subdirectory(Core)
add_subdirectory(Crypto)
add_subdirectory(Net)
add_subdirectory(NetSSL_OpenSSL)
add_subdirectory(Web)
add_subdirectory(WebServer)
add_subdirectory(SecureWebServer)
add_subdirectory(SimpleAuth)
add_subdirectory(BundleAdmin)
add_subdirectory(WebEvent)
if(PDR_ENABLE_OBSERVABILITY)
    add_subdirectory(SystemMonitoring)
endif()
add_subdirectory(StripBundle)
add_subdirectory(Unit)

if(MYIOT_ENABLE_DATA_MODULES)
    add_subdirectory(ActiveRecord)
    add_subdirectory(Data)
endif()
