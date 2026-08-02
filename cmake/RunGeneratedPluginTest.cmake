foreach(required PDR_CMAKE PDR_CTEST PDR_PYTHON PDR_SOURCE_DIR PDR_BINARY_DIR
                 PDR_CONFIG PDR_GENERATOR PDR_DEPENDENCY_PREFIX PDR_RUNTIME_FILE_NAME
                 PDR_PLUGIN_HOST_FILE_NAME PDR_LAUNCHER_FILE_NAME)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR "RunGeneratedPluginTest.cmake requires ${required}")
    endif()
endforeach()

set(root "${PDR_BINARY_DIR}/generated-plugin-consumer")
set(module_root "${root}/source")
set(module "${module_root}/ExamplePlugin")
set(broken_module "${module_root}/BrokenPlugin")
set(faulty_module "${module_root}/FaultyPlugin")
set(install "${root}/install")
set(artifacts "${root}/artifacts")
set(report "${root}/verify-report.json")
file(REMOVE_RECURSE "${root}")

execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/pdr.py"
            new plugin ExamplePlugin --output "${module_root}"
    RESULT_VARIABLE generate_result)
if(NOT generate_result EQUAL 0)
    message(FATAL_ERROR "Plugin template generation failed: ${generate_result}")
endif()
execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/pdr.py"
            new plugin BrokenPlugin --output "${module_root}"
    RESULT_VARIABLE broken_generate_result)
if(NOT broken_generate_result EQUAL 0)
    message(FATAL_ERROR "Broken plugin template generation failed: ${broken_generate_result}")
endif()
execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/pdr.py"
            new plugin FaultyPlugin --output "${module_root}"
    RESULT_VARIABLE faulty_generate_result)
if(NOT faulty_generate_result EQUAL 0)
    message(FATAL_ERROR "Faulty plugin template generation failed: ${faulty_generate_result}")
endif()
set(faulty_activator "${faulty_module}/src/BundleActivator.cpp")
file(READ "${faulty_activator}" faulty_activator_content)
string(REPLACE
    "#include <Poco/ClassLibrary.h>"
    "#include <Poco/ClassLibrary.h>\n#include <Poco/Exception.h>"
    faulty_activator_content "${faulty_activator_content}")
string(REPLACE
    "_service = new StatusService;"
    "throw Poco::RuntimeException(\"injected plugin start failure\");"
    faulty_activator_content "${faulty_activator_content}")
file(WRITE "${faulty_activator}" "${faulty_activator_content}")
set(broken_spec "${broken_module}/BrokenPlugin.bndlspec")
file(READ "${broken_spec}" broken_spec_content)
string(REPLACE
    "<pluginAbi>\${pdrPluginAbi}</pluginAbi>"
    "<pluginAbi>9.0.0</pluginAbi>"
    broken_spec_content "${broken_spec_content}")
string(REPLACE
    "</requiredBundles>"
    "  <bundle><symbolicName>pdr.missing.dependency</symbolicName><version>[1.0.0,2.0.0)</version></bundle>\n    </requiredBundles>"
    broken_spec_content "${broken_spec_content}")
file(WRITE "${broken_spec}" "${broken_spec_content}")

execute_process(
    COMMAND "${PDR_CMAKE}" --install "${PDR_BINARY_DIR}"
            --config "${PDR_CONFIG}" --prefix "${install}"
    RESULT_VARIABLE install_result)
if(NOT install_result EQUAL 0)
    message(FATAL_ERROR "Framework install for generated plugin failed: ${install_result}")
endif()

set(verify_command "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/pdr.py"
    verify "${module}"
    --cmake "${PDR_CMAKE}" --ctest "${PDR_CTEST}"
    --generator "${PDR_GENERATOR}" --config "${PDR_CONFIG}"
    --prefix "${install}" --prefix "${PDR_DEPENDENCY_PREFIX}"
    --artifact-output "${artifacts}" --report "${report}")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND verify_command --platform "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${verify_command} RESULT_VARIABLE verify_result)
if(NOT verify_result EQUAL 0)
    message(FATAL_ERROR "Generated plugin verification failed: ${verify_result}; report=${report}")
endif()
file(GLOB generated_bundles "${artifacts}/pdr.plugin.exampleplugin_*.bndl")
list(LENGTH generated_bundles generated_bundle_count)
if(NOT generated_bundle_count EQUAL 1)
    message(FATAL_ERROR "Generated plugin did not produce exactly one versioned Bundle")
endif()
list(GET generated_bundles 0 generated_bundle)
file(SIZE "${generated_bundle}" generated_bundle_size)
if(generated_bundle_size LESS 1024)
    message(FATAL_ERROR "Generated plugin Bundle is unexpectedly small")
endif()
file(SHA256 "${generated_bundle}" generated_bundle_sha256)
execute_process(
    COMMAND "${PDR_PYTHON}" "${install}/bin/pdr.py" plugin install
        "${generated_bundle}" --bundle-directory "${install}/bin/bundles"
        --expected-sha256 "${generated_bundle_sha256}" --confirm-runtime-stopped
        --allow-unsigned-plugin
        --report "${root}/plugin-install-report.json"
    RESULT_VARIABLE plugin_install_result)
if(NOT plugin_install_result EQUAL 0)
    message(FATAL_ERROR "Installed plugin transaction CLI failed: ${plugin_install_result}")
endif()
file(READ "${root}/plugin-install-report.json" plugin_install_report)
if(NOT plugin_install_report MATCHES "\"diagnosticBypass\"[ \t]*:[ \t]*true")
    message(FATAL_ERROR "Unsigned generated-plugin test must record its diagnostic bypass")
endif()

set(broken_artifacts "${root}/broken-artifacts")
set(broken_verify_command "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/pdr.py"
    verify "${broken_module}"
    --cmake "${PDR_CMAKE}" --ctest "${PDR_CTEST}"
    --generator "${PDR_GENERATOR}" --config "${PDR_CONFIG}"
    --prefix "${install}" --prefix "${PDR_DEPENDENCY_PREFIX}"
    --artifact-output "${broken_artifacts}" --report "${root}/broken-verify-report.json")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND broken_verify_command --platform "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${broken_verify_command} RESULT_VARIABLE broken_verify_result)
if(NOT broken_verify_result EQUAL 0)
    message(FATAL_ERROR "Broken dependency plugin did not package: ${broken_verify_result}")
endif()
file(GLOB broken_bundles "${broken_artifacts}/pdr.plugin.brokenplugin_*.bndl")
list(LENGTH broken_bundles broken_bundle_count)
if(NOT broken_bundle_count EQUAL 1)
    message(FATAL_ERROR "Broken dependency plugin did not produce exactly one Bundle")
endif()
list(GET broken_bundles 0 broken_bundle)
file(SHA256 "${broken_bundle}" broken_bundle_sha256)
execute_process(
    COMMAND "${PDR_PYTHON}" "${install}/bin/pdr.py" plugin preflight
        "${broken_bundle}" --bundle-directory "${install}/bin/bundles"
        --expected-sha256 "${broken_bundle_sha256}"
        --allow-unsigned-plugin
        --report "${root}/broken-plugin-preflight-report.json"
    RESULT_VARIABLE broken_preflight_result)
if(NOT broken_preflight_result EQUAL 1)
    message(FATAL_ERROR
        "Missing-dependency plugin preflight must return 1, got ${broken_preflight_result}")
endif()
file(COPY ${broken_bundles} DESTINATION "${install}/bin/bundles")

set(faulty_artifacts "${root}/faulty-artifacts")
set(faulty_verify_command "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/pdr.py"
    verify "${faulty_module}"
    --cmake "${PDR_CMAKE}" --ctest "${PDR_CTEST}"
    --generator "${PDR_GENERATOR}" --config "${PDR_CONFIG}"
    --prefix "${install}" --prefix "${PDR_DEPENDENCY_PREFIX}"
    --artifact-output "${faulty_artifacts}" --report "${root}/faulty-verify-report.json")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND faulty_verify_command --platform "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${faulty_verify_command} RESULT_VARIABLE faulty_verify_result)
if(NOT faulty_verify_result EQUAL 0)
    message(FATAL_ERROR "Faulty plugin did not package: ${faulty_verify_result}")
endif()
file(GLOB faulty_bundles "${faulty_artifacts}/pdr.plugin.faultyplugin_*.bndl")
list(LENGTH faulty_bundles faulty_bundle_count)
if(NOT faulty_bundle_count EQUAL 1)
    message(FATAL_ERROR "Faulty plugin did not produce exactly one Bundle")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/runtime_smoke.py"
        --executable "${install}/bin/${PDR_RUNTIME_FILE_NAME}"
        --working-directory "${install}/bin"
        --config "${install}/bin/pdr-runtime.properties"
        --timeout 20 --stability-window 1 --clear-code-cache
        --path "${PDR_DEPENDENCY_PREFIX}/bin" --path "${install}/bin"
        --endpoint "/health/live"
        --endpoint "/api/v1/process-detail"
        --require-body "\\\"id\\\":\\\"pdr.plugin.exampleplugin\\\""
        --require-body "\\\"governanceStatus\\\":\\\"ready\\\""
        --require-body "\\\"compatible\\\":true"
        --require-body "\\\"pluginApiVersion\\\":\\\"1.0.0\\\""
        --require-body "\\\"id\\\":\\\"pdr.plugin.brokenplugin\\\""
        --require-body "\\\"governanceStatus\\\":\\\"incompatible\\\""
        --require-body "\\\"pluginAbiVersion\\\":\\\"9.0.0\\\""
        --require-body "plugin ABI mismatch"
        --require-body "\\\"state\\\":\\\"missing\\\""
        --post "/api/v1/bundle-lifecycle={\"id\":\"pdr.plugin.brokenplugin\",\"action\":\"start\"}"
        --post-response-status "1=409"
        --require-log "ExamplePlugin plugin started"
        --report "${root}/runtime-report.json"
        --log "${root}/runtime.log"
    RESULT_VARIABLE runtime_result)
if(NOT runtime_result EQUAL 0)
    message(FATAL_ERROR "Generated plugin did not load in Runtime: ${runtime_result}")
endif()

file(COPY ${faulty_bundles} DESTINATION "${install}/bin/bundles")

execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/runtime_plugin_quarantine_integration.py"
        --executable "${install}/bin/${PDR_RUNTIME_FILE_NAME}"
        --working-directory "${install}/bin"
        --config "${install}/bin/pdr-runtime.properties"
        --plugin-id "pdr.plugin.faultyplugin"
        --workspace "${root}/quarantine-workspace"
        --path "${PDR_DEPENDENCY_PREFIX}/bin" --path "${install}/bin"
        --report "${root}/quarantine-report.json"
    RESULT_VARIABLE quarantine_result)
if(NOT quarantine_result EQUAL 0)
    message(FATAL_ERROR
        "Plugin quarantine integration failed: ${quarantine_result}; report=${root}/quarantine-report.json")
endif()

file(GLOB core_bundles "${install}/bin/bundles/osp.core_*.bndl")
list(LENGTH core_bundles core_bundle_count)
if(NOT core_bundle_count EQUAL 1)
    message(FATAL_ERROR "Plugin-host test requires exactly one osp.core Bundle")
endif()
list(GET core_bundles 0 core_bundle)
execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/plugin_host_integration.py"
        --host "${install}/bin/processes/pdr-plugin-host/${PDR_PLUGIN_HOST_FILE_NAME}"
        --launcher "${install}/bin/processes/pdr-launcher/${PDR_LAUNCHER_FILE_NAME}"
        --plugin-id "pdr.plugin.exampleplugin"
        --bundle "${core_bundle}" --bundle "${generated_bundle}" --bundle "${broken_bundle}"
        --workspace "${root}/plugin-host-workspace"
        --path "${PDR_DEPENDENCY_PREFIX}/bin" --path "${install}/bin"
        --report "${root}/plugin-host-report.json"
    RESULT_VARIABLE plugin_host_result)
if(NOT plugin_host_result EQUAL 0)
    message(FATAL_ERROR
        "Isolated plugin-host integration failed: ${plugin_host_result}; report=${root}/plugin-host-report.json")
endif()

set(scaffold_command "${PDR_PYTHON}" "${install}/bin/pdr.py" plugin scaffold-isolated
    "${generated_bundle}" --runtime-root "${install}/bin"
    --instance-name "generated-example-isolated"
    --dependency-bundle "${core_bundle}"
    --approval-report "${root}/plugin-install-report.json"
    --allow-diagnostic-bypass
    --report "${root}/isolated-scaffold-report.json")
if(WIN32)
    list(APPEND scaffold_command --memory-bytes 268435456
        --active-process-limit 1 --cpu-rate-percent 25)
endif()
execute_process(COMMAND ${scaffold_command} RESULT_VARIABLE scaffold_result)
if(NOT scaffold_result EQUAL 0)
    message(FATAL_ERROR "Isolated plugin deployment scaffold failed: ${scaffold_result}")
endif()
file(READ "${root}/isolated-scaffold-report.json" scaffold_report)
if(NOT scaffold_report MATCHES "\"passed\"[ \t]*:[ \t]*true" OR
   NOT scaffold_report MATCHES "\"pluginId\"[ \t]*:[ \t]*\"pdr.plugin.exampleplugin\"")
    message(FATAL_ERROR "Isolated plugin deployment scaffold report is incomplete")
endif()

set(isolated_instance "${install}/bin/processes/generated-example-isolated")
set(isolated_subprocess_config "${install}/bin/pdr-subprocesses.generated-test.properties")
execute_process(
    COMMAND "${PDR_PYTHON}" "${install}/bin/pdr.py" plugin apply-isolated
        generated-example-isolated --runtime-root "${install}/bin"
        --configuration "${isolated_subprocess_config}" --confirm-runtime-stopped
        --report "${root}/isolated-apply-report.json"
    RESULT_VARIABLE isolated_apply_result)
if(NOT isolated_apply_result EQUAL 0)
    message(FATAL_ERROR "Isolated plugin lifecycle apply failed: ${isolated_apply_result}")
endif()
execute_process(
    COMMAND "${PDR_PYTHON}" "${install}/bin/pdr.py" plugin list-isolated
        --runtime-root "${install}/bin" --configuration "${isolated_subprocess_config}"
        --report "${root}/isolated-list-report.json"
    RESULT_VARIABLE isolated_list_result)
if(NOT isolated_list_result EQUAL 0)
    message(FATAL_ERROR "Isolated plugin lifecycle list failed: ${isolated_list_result}")
endif()
execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/runtime_smoke.py"
        --executable "${install}/bin/${PDR_RUNTIME_FILE_NAME}"
        --working-directory "${install}/bin"
        --config "${install}/bin/pdr-runtime.properties"
        --timeout 20 --stability-window 1 --probe-delay 1 --clear-code-cache
        --path "${PDR_DEPENDENCY_PREFIX}/bin" --path "${install}/bin"
        --set "pdr.subprocess.configuration=${isolated_subprocess_config}"
        --endpoint "/api/v1/process-detail?id=generated-example-isolated&name=generated-example-isolated"
        --require-body "\"id\":\"pdr.plugin.exampleplugin\""
        --require-body "\"isolation\":\"process\""
        --require-body "\"plugin\":true"
        --report "${root}/isolated-runtime-web-report.json"
        --log "${root}/isolated-runtime-web.log"
    RESULT_VARIABLE isolated_web_result)
if(NOT isolated_web_result EQUAL 0)
    message(FATAL_ERROR
        "Isolated plugin was not visible through Runtime process detail: ${isolated_web_result}")
endif()
execute_process(
    COMMAND "${PDR_PYTHON}" "${install}/bin/pdr.py" plugin remove-isolated
        generated-example-isolated --runtime-root "${install}/bin"
        --configuration "${isolated_subprocess_config}" --confirm-runtime-stopped --purge
        --report "${root}/isolated-remove-report.json"
    RESULT_VARIABLE isolated_remove_result)
if(NOT isolated_remove_result EQUAL 0 OR EXISTS "${isolated_instance}")
    message(FATAL_ERROR "Isolated plugin lifecycle remove failed: ${isolated_remove_result}")
endif()
