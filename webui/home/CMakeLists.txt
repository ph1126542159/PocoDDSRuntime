if(WIN32)
    find_program(PDR_WEBUI_NPM_EXECUTABLE NAMES npm.cmd REQUIRED)
else()
    find_program(PDR_WEBUI_NPM_EXECUTABLE NAMES npm REQUIRED)
endif()
file(GLOB_RECURSE pdr_webui_home_sources CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/*"
    "${CMAKE_CURRENT_SOURCE_DIR}/static/*")
set(pdr_webui_home_assets_output
    "${CMAKE_CURRENT_SOURCE_DIR}/bundle/webui/index.html")
add_custom_target(pdr_webui_home_Assets
    COMMAND "${PDR_WEBUI_NPM_EXECUTABLE}" ci --no-audit --no-fund
    COMMAND "${PDR_WEBUI_NPM_EXECUTABLE}" run build
    BYPRODUCTS "${pdr_webui_home_assets_output}"
    DEPENDS ${pdr_webui_home_sources}
            "${CMAKE_CURRENT_SOURCE_DIR}/package.json"
            "${CMAKE_CURRENT_SOURCE_DIR}/package-lock.json"
            "${CMAKE_CURRENT_SOURCE_DIR}/vite.config.js"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    VERBATIM)
pdr_add_webui_bundle(pdr_webui_home pdr-webui-home.bndlspec
    GENERATED_RESOURCES "${pdr_webui_home_assets_output}")
add_dependencies(pdr_webui_home_Package pdr_webui_home_Assets)
