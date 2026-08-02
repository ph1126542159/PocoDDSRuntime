foreach(required PDR_CMAKE PDR_PYTHON PDR_SOURCE_DIR PDR_BINARY_DIR
                 PDR_DEPENDENCY_PREFIX PDR_CONFIG PDR_RUNTIME_FILE_NAME
                 PDR_CONFIG_CHECK_FILE_NAME PDR_SIGNATURE_CHECK_FILE_NAME
                 PDR_IDENTITY_CHECK_FILE_NAME)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR "RunRuntimePackageSmoke.cmake requires ${required}")
    endif()
endforeach()

set(prefix "${PDR_BINARY_DIR}/runtime-smoke-install")
set(report "${PDR_BINARY_DIR}/reports/runtime-package-smoke.json")
file(REMOVE_RECURSE "${prefix}")

execute_process(
    COMMAND "${PDR_CMAKE}" --install "${PDR_BINARY_DIR}"
            --config "${PDR_CONFIG}" --prefix "${prefix}"
    RESULT_VARIABLE install_result
    OUTPUT_VARIABLE install_output
    ERROR_VARIABLE install_error)
if(NOT install_result EQUAL 0)
    message(FATAL_ERROR
        "Runtime package install failed (${install_result})\n${install_output}\n${install_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" identity --help
    RESULT_VARIABLE identity_help_result
    OUTPUT_VARIABLE identity_help_output
    ERROR_VARIABLE identity_help_error)
if(NOT identity_help_result EQUAL 0 OR
        NOT identity_help_output MATCHES "inspect" OR
        NOT identity_help_output MATCHES "check" OR
        NOT EXISTS "${prefix}/bin/${PDR_IDENTITY_CHECK_FILE_NAME}")
    message(FATAL_ERROR
        "Installed identity CLI is unavailable (${identity_help_result})\n"
        "${identity_help_output}\n${identity_help_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" upgrade preflight --help
    RESULT_VARIABLE upgrade_preflight_help_result
    OUTPUT_VARIABLE upgrade_preflight_help_output
    ERROR_VARIABLE upgrade_preflight_help_error)
if(NOT upgrade_preflight_help_result EQUAL 0 OR
        NOT upgrade_preflight_help_output MATCHES "trust-policy" OR
        NOT upgrade_preflight_help_output MATCHES "expected-public-key-sha256" OR
        NOT upgrade_preflight_help_output MATCHES "signature-check-executable")
    message(FATAL_ERROR
        "Installed signed upgrade preflight CLI is incomplete (${upgrade_preflight_help_result})\n"
        "${upgrade_preflight_help_output}\n${upgrade_preflight_help_error}")
endif()

set(installed_python_tools
    pdr.py
    release_manifest.py
    release_qualification.py
    external_acceptance.py
    evidence_bundle.py
    release_pipeline.py
    upgrade_manager.py
    plugin_manager.py
    runtime_smoke.py
    soak_runner.py
    device_acceptance.py
    protocol_acceptance.py
    security_gate.py)
foreach(installed_tool ${installed_python_tools} pdr.ps1 "${PDR_CONFIG_CHECK_FILE_NAME}")
    if(NOT EXISTS "${prefix}/bin/${installed_tool}")
        message(FATAL_ERROR "Installed Runtime package is missing CLI tool: ${installed_tool}")
    endif()
endforeach()
if(NOT EXISTS "${prefix}/bin/${PDR_SIGNATURE_CHECK_FILE_NAME}")
    message(FATAL_ERROR
        "Installed Runtime package is missing signature verifier: ${PDR_SIGNATURE_CHECK_FILE_NAME}")
endif()
set(bundle_creator_name "bundle")
if(WIN32)
    set(bundle_creator_name "bundle.exe")
endif()
if(NOT EXISTS "${prefix}/lib/cmake/PocoDDSRuntime/PocoDDSPlugins.cmake" OR
        NOT EXISTS "${prefix}/bin/${bundle_creator_name}" OR
        NOT EXISTS "${prefix}/bin/pdr-plugin-runtime.json")
    message(FATAL_ERROR
        "Installed Runtime package is missing the Plugins CMake API or BundleCreator")
endif()
file(READ "${prefix}/bin/pdr-plugin-runtime.json" plugin_runtime_contract)
foreach(required_contract_field runtimeVersion pluginApiVersion pluginAbiVersion abiFingerprint)
    if(NOT plugin_runtime_contract MATCHES "\"${required_contract_field}\"[ \t]*:")
        message(FATAL_ERROR
            "Installed plugin Runtime contract is missing ${required_contract_field}")
    endif()
endforeach()
foreach(installed_tool IN LISTS installed_python_tools)
    execute_process(
        COMMAND "${PDR_PYTHON}" "${prefix}/bin/${installed_tool}" --help
        RESULT_VARIABLE help_result
        OUTPUT_VARIABLE help_output
        ERROR_VARIABLE help_error)
    if(NOT help_result EQUAL 0 OR NOT help_output MATCHES "usage:")
        message(FATAL_ERROR
            "Installed tool cannot start: ${installed_tool} (${help_result})\n"
            "${help_output}\n${help_error}")
    endif()
endforeach()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" doctor
            --dependency-prefix "${PDR_DEPENDENCY_PREFIX}"
            --report "${PDR_BINARY_DIR}/reports/runtime-package-doctor.json"
    RESULT_VARIABLE doctor_result
    OUTPUT_VARIABLE doctor_output
    ERROR_VARIABLE doctor_error)
if(NOT doctor_result EQUAL 0)
    message(FATAL_ERROR
        "Installed CLI doctor failed (${doctor_result})\n${doctor_output}\n${doctor_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" persistence --help
    RESULT_VARIABLE persistence_help_result
    OUTPUT_VARIABLE persistence_help_output
    ERROR_VARIABLE persistence_help_error)
if(NOT persistence_help_result EQUAL 0 OR
        NOT persistence_help_output MATCHES "inspect" OR
        NOT persistence_help_output MATCHES "recover" OR
        NOT persistence_help_output MATCHES "backup" OR
        NOT persistence_help_output MATCHES "verify-recovery-point" OR
        NOT persistence_help_output MATCHES "restore-recovery-point" OR
        NOT persistence_help_output MATCHES "validate-restored-runtime")
    message(FATAL_ERROR
        "Installed persistence CLI is unavailable (${persistence_help_result})\n"
        "${persistence_help_output}\n${persistence_help_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" upgrade --help
    RESULT_VARIABLE upgrade_help_result
    OUTPUT_VARIABLE upgrade_help_output
    ERROR_VARIABLE upgrade_help_error)
if(NOT upgrade_help_result EQUAL 0 OR
        NOT upgrade_help_output MATCHES "preflight" OR
        NOT upgrade_help_output MATCHES "apply" OR
        NOT upgrade_help_output MATCHES "rollback" OR
        NOT upgrade_help_output MATCHES "recover")
    message(FATAL_ERROR
        "Installed upgrade CLI is unavailable (${upgrade_help_result})\n"
        "${upgrade_help_output}\n${upgrade_help_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" plugin --help
    RESULT_VARIABLE plugin_help_result
    OUTPUT_VARIABLE plugin_help_output
    ERROR_VARIABLE plugin_help_error)
if(NOT plugin_help_result EQUAL 0 OR
        NOT plugin_help_output MATCHES "sign" OR
        NOT plugin_help_output MATCHES "preflight" OR
        NOT plugin_help_output MATCHES "install" OR
        NOT plugin_help_output MATCHES "rollback" OR
        NOT plugin_help_output MATCHES "recover")
    message(FATAL_ERROR
        "Installed plugin transaction CLI is unavailable (${plugin_help_result})\n"
        "${plugin_help_output}\n${plugin_help_error}")
endif()
execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" plugin preflight --help
    RESULT_VARIABLE plugin_preflight_help_result
    OUTPUT_VARIABLE plugin_preflight_help_output
    ERROR_VARIABLE plugin_preflight_help_error)
if(NOT plugin_preflight_help_result EQUAL 0 OR
        NOT plugin_preflight_help_output MATCHES "attestation" OR
        NOT plugin_preflight_help_output MATCHES "trust-policy" OR
        NOT plugin_preflight_help_output MATCHES "allow-unsigned-plugin")
    message(FATAL_ERROR
        "Installed plugin provenance CLI is incomplete (${plugin_preflight_help_result})\n"
        "${plugin_preflight_help_output}\n${plugin_preflight_help_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" validate-config
            "${prefix}/bin/pdr-runtime.properties"
            --report "${PDR_BINARY_DIR}/reports/runtime-package-config-validation.json"
    RESULT_VARIABLE config_check_result
    OUTPUT_VARIABLE config_check_output
    ERROR_VARIABLE config_check_error)
if(NOT config_check_result EQUAL 0)
    message(FATAL_ERROR
        "Installed runtime configuration validation failed (${config_check_result})\n"
        "${config_check_output}\n${config_check_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${PDR_SOURCE_DIR}/tools/runtime_smoke.py"
            --executable "${prefix}/bin/${PDR_RUNTIME_FILE_NAME}"
            --working-directory "${prefix}/bin"
            --timeout 20
            --stability-window 2
            --path "${prefix}/bin"
            --endpoint "/health/detail"
            --report "${report}"
    RESULT_VARIABLE smoke_result
    OUTPUT_VARIABLE smoke_output
    ERROR_VARIABLE smoke_error)
if(NOT smoke_result EQUAL 0)
    file(READ "${report}" report_content)
    message(FATAL_ERROR
        "Installed runtime smoke failed (${smoke_result})\n${smoke_output}\n${smoke_error}\n${report_content}")
endif()

message(STATUS
    "${doctor_output}${persistence_help_output}${upgrade_help_output}${config_check_output}${smoke_output}")
