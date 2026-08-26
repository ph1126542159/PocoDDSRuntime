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
set(pdr_webui_home_model_output
    "${CMAKE_CURRENT_SOURCE_DIR}/bundle/webui/framework-model.json")
if(NOT PDR_FRAMEWORK_MODEL_MANIFEST OR
   NOT EXISTS "${PDR_FRAMEWORK_MODEL_MANIFEST}")
    message(FATAL_ERROR "The CMake framework model manifest is required by Home WebUI")
endif()
add_custom_target(pdr_webui_home_Assets
    COMMAND "${PDR_WEBUI_NPM_EXECUTABLE}" ci --no-audit --no-fund
    COMMAND "${PDR_WEBUI_NPM_EXECUTABLE}" run build
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
        "${PDR_FRAMEWORK_MODEL_MANIFEST}"
        "${pdr_webui_home_model_output}"
    BYPRODUCTS "${pdr_webui_home_assets_output}"
               "${pdr_webui_home_model_output}"
    DEPENDS ${pdr_webui_home_sources}
            "${PDR_FRAMEWORK_MODEL_MANIFEST}"
            "${CMAKE_CURRENT_SOURCE_DIR}/package.json"
            "${CMAKE_CURRENT_SOURCE_DIR}/package-lock.json"
            "${CMAKE_CURRENT_SOURCE_DIR}/vite.config.js"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    VERBATIM)
pdr_add_webui_bundle(pdr_webui_home pdr-webui-home.bndlspec
    GENERATED_RESOURCES "${pdr_webui_home_assets_output}")
add_dependencies(pdr_webui_home_Package pdr_webui_home_Assets)

if(BUILD_TESTING)
    find_program(PDR_WEBUI_NODE_EXECUTABLE NAMES node node.exe REQUIRED)
    add_test(NAME webui-framework-model
        COMMAND "${PDR_WEBUI_NODE_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/framework-model.test.mjs")
    set_tests_properties(webui-framework-model PROPERTIES
        LABELS "webui;contract;framework"
        PASS_REGULAR_EXPRESSION "PDR_WEBUI_FRAMEWORK_MODEL_PASS")
    add_test(NAME webui-process-dependency-model
        COMMAND "${PDR_WEBUI_NODE_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/process-dependency-model.test.mjs")
    set_tests_properties(webui-process-dependency-model PROPERTIES
        LABELS "webui;contract;process-management"
        PASS_REGULAR_EXPRESSION "PDR_WEBUI_PROCESS_DEPENDENCY_MODEL_PASS")
endif()
