pdr_add_webui_bundle(pdr_webui_home pdr-webui-home.bndlspec)

find_program(PDR_NPM_EXECUTABLE NAMES npm npm.cmd REQUIRED)
file(GLOB_RECURSE pdr_webui_home_sources CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/*"
    "${CMAKE_CURRENT_SOURCE_DIR}/static/*")
set(pdr_webui_home_assets_output
    "${CMAKE_CURRENT_SOURCE_DIR}/bundle/webui/index.html")
add_custom_command(
    OUTPUT "${pdr_webui_home_assets_output}"
    COMMAND "${PDR_NPM_EXECUTABLE}" run build
    DEPENDS ${pdr_webui_home_sources}
            "${CMAKE_CURRENT_SOURCE_DIR}/package.json"
            "${CMAKE_CURRENT_SOURCE_DIR}/vite.config.js"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    VERBATIM)
add_custom_target(pdr_webui_home_Assets DEPENDS "${pdr_webui_home_assets_output}")
add_dependencies(pdr_webui_home_Package pdr_webui_home_Assets)
