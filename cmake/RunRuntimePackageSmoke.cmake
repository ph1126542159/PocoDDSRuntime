foreach(required PDR_CMAKE PDR_PYTHON PDR_SOURCE_DIR PDR_BINARY_DIR
                 PDR_DEPENDENCY_PREFIX PDR_CONFIG PDR_RUNTIME_FILE_NAME
                 PDR_CONFIG_CHECK_FILE_NAME PDR_SIGNATURE_CHECK_FILE_NAME
                 PDR_IDENTITY_CHECK_FILE_NAME PDR_FASTDDS_PROFILE_CHECK_FILE_NAME)
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

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/team_contract_registry_remote.py" --help
    RESULT_VARIABLE remote_registry_help_result
    OUTPUT_VARIABLE remote_registry_help_output
    ERROR_VARIABLE remote_registry_help_error)
if(NOT remote_registry_help_result EQUAL 0 OR
        NOT remote_registry_help_output MATCHES "serve" OR
        NOT remote_registry_help_output MATCHES "publish" OR
        NOT remote_registry_help_output MATCHES "resolve" OR
        NOT remote_registry_help_output MATCHES "status" OR
        NOT remote_registry_help_output MATCHES "capacity" OR
        NOT remote_registry_help_output MATCHES "lease-status" OR
        NOT remote_registry_help_output MATCHES "recover" OR
        NOT remote_registry_help_output MATCHES "audit-checkpoint" OR
        NOT remote_registry_help_output MATCHES "audit-archive-status")
    message(FATAL_ERROR
        "Installed remote team contract Registry CLI is incomplete "
        "(${remote_registry_help_result})\n${remote_registry_help_output}\n"
        "${remote_registry_help_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}"
        "${prefix}/bin/team_contract_registry_access_policy.py" --help
    RESULT_VARIABLE access_policy_help_result
    OUTPUT_VARIABLE access_policy_help_output
    ERROR_VARIABLE access_policy_help_error)
if(NOT access_policy_help_result EQUAL 0 OR
        NOT access_policy_help_output MATCHES "sign" OR
        NOT access_policy_help_output MATCHES "activate")
    message(FATAL_ERROR
        "Installed Registry access-policy rotation CLI is incomplete "
        "(${access_policy_help_result})\n${access_policy_help_output}\n"
        "${access_policy_help_error}")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" contract-package --help
    RESULT_VARIABLE team_contract_help_result
    OUTPUT_VARIABLE team_contract_help_output
    ERROR_VARIABLE team_contract_help_error)
if(NOT team_contract_help_result EQUAL 0 OR
        NOT team_contract_help_output MATCHES "impact-execute" OR
        NOT team_contract_help_output MATCHES "impact-approve" OR
        NOT team_contract_help_output MATCHES "impact-gate" OR
        NOT team_contract_help_output MATCHES "registry-promote" OR
        NOT team_contract_help_output MATCHES "registry-resolve" OR
        NOT team_contract_help_output MATCHES "runner-attest" OR
        NOT team_contract_help_output MATCHES "gate-authorize" OR
        NOT team_contract_help_output MATCHES "registry-access-policy-sign" OR
        NOT team_contract_help_output MATCHES "registry-remote-capacity" OR
        NOT team_contract_help_output MATCHES "registry-lease-status" OR
        NOT team_contract_help_output MATCHES "registry-remote-lease-status" OR
        NOT team_contract_help_output MATCHES "registry-remote-audit-archive-create" OR
        NOT team_contract_help_output MATCHES "registry-remote-audit-archive-prune" OR
        NOT team_contract_help_output MATCHES "registry-recovery-create" OR
        NOT team_contract_help_output MATCHES "registry-recovery-restore" OR
        NOT team_contract_help_output MATCHES "registry-standby-init" OR
        NOT team_contract_help_output MATCHES "registry-standby-sync" OR
        NOT team_contract_help_output MATCHES "registry-leader-issue" OR
        NOT team_contract_help_output MATCHES "registry-leader-activate" OR
        NOT team_contract_help_output MATCHES "registry-leader-backend-capabilities" OR
        NOT team_contract_help_output MATCHES "registry-leader-backend-conformance" OR
        NOT team_contract_help_output MATCHES "artifact-store-put" OR
        NOT team_contract_help_output MATCHES "artifact-store-get" OR
        NOT team_contract_help_output MATCHES "backend-config-resolve" OR
        NOT team_contract_help_output MATCHES "adapter-conformance" OR
        NOT team_contract_help_output MATCHES "registry-leader-backend-migration-sync" OR
        NOT team_contract_help_output MATCHES "registry-leader-backend-migration-finalize" OR
        NOT team_contract_help_output MATCHES "registry-leader-backend-migration-status" OR
        NOT team_contract_help_output MATCHES "registry-leader-backend-migration-resume" OR
        NOT team_contract_help_output MATCHES "registry-leader-backend-migration-reconcile" OR
        NOT team_contract_help_output MATCHES "registry-leader-backend-migration-abort" OR
        NOT team_contract_help_output MATCHES "registry-leader-etcd-preflight" OR
        NOT team_contract_help_output MATCHES "registry-leader-etcd-acceptance" OR
        NOT team_contract_help_output MATCHES "registry-drain-start" OR
        NOT team_contract_help_output MATCHES "registry-drain-finalize" OR
        NOT team_contract_help_output MATCHES "registry-remote-drain-start" OR
        NOT team_contract_help_output MATCHES "registry-remote-drain-finalize" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-activate" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-rollback" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-current-check" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-state-verify" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-reconcile" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-reconcile-recover" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-reconcile-revert" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-reconcile-status" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-fleet-run" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-fleet-recover" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-fleet-status" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-fleet-resume" OR
        NOT team_contract_help_output MATCHES "adapter-catalog-fleet-abort" OR
        NOT team_contract_help_output MATCHES "registry-anchor-verify")
    message(FATAL_ERROR
        "Installed team contract impact gate CLI is incomplete "
        "(${team_contract_help_result})\n${team_contract_help_output}\n"
        "${team_contract_help_error}")
endif()

set(installed_python_tools
    pdr.py
    release_manifest.py
    framework_change_impact.py
    framework_dependency_boundary.py
    framework_link_dependency_boundary.py
    framework_recovery_matrix.py
    component_contract_test.py
    configuration_participant_contract.py
    configuration_key_lifecycle.py
    team_contract_package.py
    team_contract_impact.py
    team_contract_impact_gate.py
    team_contract_registry.py
    team_contract_provenance.py
    team_contract_registry_remote.py
    team_contract_registry_audit_archive.py
    team_contract_registry_recovery.py
    team_contract_registry_standby.py
    team_contract_registry_leader.py
    team_contract_registry_leader_backend_capabilities.py
    team_contract_registry_leader_backend_migration.py
    team_contract_artifact_store.py
    team_contract_backend_config_resolver.py
    team_contract_adapter_config_resolver.py
    team_contract_adapter_conformance.py
    team_contract_adapter_conformance_admission.py
    team_contract_adapter_conformance_trust.py
    team_contract_secret_provider.py
    team_contract_adapter_runtime.py
    team_contract_adapter_catalog.py
    team_contract_adapter_catalog_state.py
    team_contract_adapter_catalog_reconciler.py
    team_contract_adapter_catalog_fleet.py
    team_contract_adapter_catalog_fleet_state_store.py
    team_contract_adapter_catalog_wave_gate.py
    team_contract_adapter_catalog_control_authorizer.py
    team_contract_registry_leader_etcd_acceptance.py
    team_contract_registry_handoff.py
    team_contract_registry_access_policy.py
    process_file_lease.py
    sdk_surface_guard.py
    sdk_deprecation_guard.py
    sdk_header_self_containment.py
    repository_ownership.py
    release_qualification.py
    external_acceptance.py
    evidence_bundle.py
    release_pipeline.py
    upgrade_manager.py
    bundle_repository_publisher.py
    bundle_repository_recovery.py
    bundle_repository_break_glass.py
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
foreach(config_resolver_example_file
        file_backend_config_resolver_adapter.py create_resolver_config.py README.md)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/examples/team-contract-backend-config-resolver-file/${config_resolver_example_file}")
        message(FATAL_ERROR
            "Installed Runtime package is missing Backend Config Resolver SDK example: "
            "${config_resolver_example_file}")
    endif()
endforeach()
foreach(adapter_config_resolver_example_file
        file_adapter_config_resolver_adapter.py create_resolver_config.py README.md)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/examples/team-contract-adapter-config-resolver-file/${adapter_config_resolver_example_file}")
        message(FATAL_ERROR
            "Installed Runtime package is missing Adapter Config Resolver SDK example: "
            "${adapter_config_resolver_example_file}")
    endif()
endforeach()
foreach(config_resolver_schema
        team-contract-backend-config-reference.schema.json
        team-contract-backend-config-resolver-config.schema.json
        team-contract-backend-config-resolver-capability-request.schema.json
        team-contract-backend-config-resolver-capability-manifest.schema.json
        team-contract-backend-config-resolver-request.schema.json
        team-contract-backend-config-resolver-response.schema.json
    team-contract-adapter-config-reference.schema.json
    team-contract-adapter-config-resolver-config.schema.json
    team-contract-adapter-config-resolver-capability-request.schema.json
    team-contract-adapter-config-resolver-capability-manifest.schema.json
    team-contract-adapter-config-resolver-request.schema.json
    team-contract-adapter-config-resolver-response.schema.json
    team-contract-adapter-conformance-evidence.schema.json
    team-contract-adapter-conformance-admission-bundle.schema.json
    team-contract-adapter-conformance-attestation.schema.json
    team-contract-adapter-conformance-trust-policy.schema.json
    team-contract-secret-reference.schema.json
    team-contract-secret-provider-config.schema.json
    team-contract-secret-provider-capability-request.schema.json
    team-contract-secret-provider-capability-manifest.schema.json
    team-contract-secret-provider-request.schema.json
    team-contract-secret-provider-response.schema.json
    team-contract-secret-provider-check.schema.json)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/contracts/schemas/${config_resolver_schema}")
        message(FATAL_ERROR
            "Installed Runtime package is missing Backend Config Resolver schema: "
            "${config_resolver_schema}")
    endif()
endforeach()
foreach(secret_provider_example_file
        environment_secret_provider_adapter.py create_secret_provider_config.py README.md)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/examples/team-contract-secret-provider-environment/${secret_provider_example_file}")
        message(FATAL_ERROR
            "Installed Runtime package is missing Secret Provider SDK example: "
            "${secret_provider_example_file}")
    endif()
endforeach()
foreach(adapter_catalog_example_file
        create_adapter_manifest.py create_adapter_catalog.py
        create_reconciler_config.py lifecycle_reconciler_adapter.py
        create_fleet_node_map.py create_fleet_executor_config.py
        create_fleet_plan.py create_conformance_trust_demo.py
        fleet_node_executor_adapter.py
        create_wave_gate_config.py wave_gate_adapter.py
        create_control_authorizer_config.py control_authorizer_adapter.py README.md)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/${adapter_catalog_example_file}")
        message(FATAL_ERROR
            "Installed Runtime package is missing Adapter Catalog SDK example: "
            "${adapter_catalog_example_file}")
    endif()
endforeach()
foreach(adapter_catalog_schema
        team-contract-adapter-manifest.schema.json
        team-contract-adapter-catalog.schema.json
        team-contract-adapter-catalog-listing.schema.json
        team-contract-adapter-catalog-check.schema.json
        team-contract-adapter-catalog-pointer.schema.json
        team-contract-adapter-catalog-state.schema.json
        team-contract-adapter-catalog-state-operation.schema.json
        team-contract-adapter-catalog-current.schema.json
        team-contract-adapter-catalog-current-check.schema.json
        team-contract-adapter-catalog-state-verification.schema.json
        team-contract-adapter-catalog-reconciler-config.schema.json
        team-contract-adapter-catalog-reconciler-capability-request.schema.json
        team-contract-adapter-catalog-reconciler-capability-manifest.schema.json
        team-contract-adapter-catalog-reconciler-request.schema.json
        team-contract-adapter-catalog-reconciler-response.schema.json
        team-contract-adapter-catalog-reconcile-journal.schema.json
        team-contract-adapter-catalog-reconcile-report.schema.json
        team-contract-adapter-catalog-reconcile-status.schema.json
        team-contract-adapter-catalog-fleet-plan.schema.json
        team-contract-adapter-catalog-fleet-executor-config.schema.json
        team-contract-adapter-catalog-fleet-executor-capability-request.schema.json
        team-contract-adapter-catalog-fleet-executor-capability-manifest.schema.json
        team-contract-adapter-catalog-fleet-executor-request.schema.json
        team-contract-adapter-catalog-fleet-executor-response.schema.json
        team-contract-adapter-catalog-fleet-node-map.schema.json
        team-contract-adapter-catalog-fleet-journal.schema.json
        team-contract-adapter-catalog-fleet-report.schema.json
        team-contract-adapter-catalog-fleet-status.schema.json
        team-contract-adapter-catalog-fleet-state-pointer.schema.json
        team-contract-adapter-catalog-wave-gate-config.schema.json
        team-contract-adapter-catalog-wave-gate-capability-request.schema.json
        team-contract-adapter-catalog-wave-gate-capability-manifest.schema.json
        team-contract-adapter-catalog-wave-gate-request.schema.json
        team-contract-adapter-catalog-wave-gate-response.schema.json
        team-contract-adapter-catalog-control-authorizer-config.schema.json
        team-contract-adapter-catalog-control-authorizer-capability-request.schema.json
        team-contract-adapter-catalog-control-authorizer-capability-manifest.schema.json
        team-contract-adapter-catalog-control-authorizer-request.schema.json
        team-contract-adapter-catalog-control-authorizer-response.schema.json)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/contracts/schemas/${adapter_catalog_schema}")
        message(FATAL_ERROR
            "Installed Runtime package is missing Adapter Catalog schema: "
            "${adapter_catalog_schema}")
    endif()
endforeach()
foreach(artifact_store_example_file
        file_artifact_store_adapter.py create_artifact_store_config.py README.md)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/examples/team-contract-artifact-store-file/${artifact_store_example_file}")
        message(FATAL_ERROR
            "Installed Runtime package is missing Artifact Store SDK example: "
            "${artifact_store_example_file}")
    endif()
endforeach()
foreach(artifact_store_schema
        team-contract-artifact-store-config.schema.json
        team-contract-artifact-reference.schema.json
        team-contract-artifact-store-capability-request.schema.json
        team-contract-artifact-store-capability-manifest.schema.json
        team-contract-artifact-store-request.schema.json
        team-contract-artifact-store-response.schema.json)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/contracts/schemas/${artifact_store_schema}")
        message(FATAL_ERROR
            "Installed Runtime package is missing Artifact Store schema: "
            "${artifact_store_schema}")
    endif()
endforeach()
foreach(leader_backend_example_file
        file_backend_adapter.py create_backend_config.py README.md)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-file/${leader_backend_example_file}")
        message(FATAL_ERROR
            "Installed Runtime package is missing leader backend SDK example: "
            "${leader_backend_example_file}")
    endif()
endforeach()
foreach(leader_etcd_example_file
        etcd_backend_adapter.py create_backend_configs.py
        etcd_cluster_preflight.py README.md)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl/${leader_etcd_example_file}")
        message(FATAL_ERROR
            "Installed Runtime package is missing leader etcd SDK example: "
            "${leader_etcd_example_file}")
    endif()
endforeach()
foreach(leader_etcd_schema
        team-contract-registry-leader-etcd-adapter-config.schema.json
        team-contract-registry-leader-etcd-preflight.schema.json
        team-contract-registry-leader-etcd-acceptance.schema.json)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/contracts/schemas/${leader_etcd_schema}")
        message(FATAL_ERROR
            "Installed Runtime package is missing leader etcd schema: "
            "${leader_etcd_schema}")
    endif()
endforeach()
foreach(leader_backend_capability_schema
        team-contract-registry-leader-backend-capability-request.schema.json
        team-contract-registry-leader-backend-capability-manifest.schema.json
        team-contract-registry-leader-backend-capability-report.schema.json)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/contracts/schemas/${leader_backend_capability_schema}")
        message(FATAL_ERROR
            "Installed Runtime package is missing leader backend capability schema: "
            "${leader_backend_capability_schema}")
    endif()
endforeach()
foreach(leader_backend_migration_schema
        team-contract-registry-leader-backend-migration-sync.schema.json
        team-contract-registry-leader-backend-migration.schema.json
        team-contract-registry-leader-backend-migration-transaction.schema.json
        team-contract-registry-leader-backend-migration-status.schema.json
        team-contract-registry-leader-backend-migration-abort.schema.json)
    if(NOT EXISTS
            "${prefix}/share/PocoDDSRuntime/contracts/schemas/${leader_backend_migration_schema}")
        message(FATAL_ERROR
            "Installed Runtime package is missing leader backend migration schema: "
            "${leader_backend_migration_schema}")
    endif()
endforeach()
if(NOT EXISTS "${prefix}/bin/project_config_transaction.py" OR
        NOT EXISTS "${prefix}/bin/project_config_approval.py" OR
        NOT EXISTS "${prefix}/bin/project_config_audit.py" OR
        NOT EXISTS "${prefix}/bin/project_config_audit_checkpoint.py" OR
        NOT EXISTS "${prefix}/bin/project_config_status.py")
    message(FATAL_ERROR
        "Installed Runtime package is missing project configuration transaction modules")
endif()
if(NOT EXISTS "${prefix}/bin/service_contract_graph.py")
    message(FATAL_ERROR
        "Installed Runtime package is missing service contract graph tooling")
endif()
execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" project config --help
    RESULT_VARIABLE project_config_help_result
    OUTPUT_VARIABLE project_config_help_output
    ERROR_VARIABLE project_config_help_error)
if(NOT project_config_help_result EQUAL 0 OR
        NOT project_config_help_output MATCHES "preflight" OR
        NOT project_config_help_output MATCHES "approval-request" OR
        NOT project_config_help_output MATCHES "approve" OR
        NOT project_config_help_output MATCHES "apply" OR
        NOT project_config_help_output MATCHES "recover" OR
        NOT project_config_help_output MATCHES "status" OR
        NOT project_config_help_output MATCHES "verify-audit" OR
        NOT project_config_help_output MATCHES "audit-checkpoint" OR
        NOT project_config_help_output MATCHES "verify-audit-checkpoint")
    message(FATAL_ERROR
        "Installed project configuration transaction CLI is incomplete "
        "(${project_config_help_result})\n${project_config_help_output}\n"
        "${project_config_help_error}")
endif()
execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py" service-contract --help
    RESULT_VARIABLE service_contract_help_result
    OUTPUT_VARIABLE service_contract_help_output
    ERROR_VARIABLE service_contract_help_error)
if(NOT service_contract_help_result EQUAL 0 OR
        NOT service_contract_help_output MATCHES "graph" OR
        NOT service_contract_help_output MATCHES "verify" OR
        NOT service_contract_help_output MATCHES "baseline-snapshot")
    message(FATAL_ERROR
        "Installed service contract graph CLI is incomplete "
        "(${service_contract_help_result})\n${service_contract_help_output}\n"
        "${service_contract_help_error}")
endif()
execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/bundle_repository_break_glass.py" --help
    RESULT_VARIABLE break_glass_help_result
    OUTPUT_VARIABLE break_glass_help_output
    ERROR_VARIABLE break_glass_help_error)
if(NOT break_glass_help_result EQUAL 0 OR
        NOT break_glass_help_output MATCHES "request" OR
        NOT break_glass_help_output MATCHES "approve" OR
        NOT break_glass_help_output MATCHES "preflight" OR
        NOT break_glass_help_output MATCHES "apply" OR
        NOT break_glass_help_output MATCHES "recover" OR
        NOT break_glass_help_output MATCHES "verify-audit")
    message(FATAL_ERROR
        "Installed Bundle break-glass CLI is incomplete (${break_glass_help_result})\n"
        "${break_glass_help_output}\n${break_glass_help_error}")
endif()
if(NOT EXISTS "${prefix}/bin/${PDR_SIGNATURE_CHECK_FILE_NAME}")
    message(FATAL_ERROR
        "Installed Runtime package is missing signature verifier: ${PDR_SIGNATURE_CHECK_FILE_NAME}")
endif()
if(NOT EXISTS
        "${prefix}/share/PocoDDSRuntime/examples/bundle-break-glass-trust-policy.example.json")
    message(FATAL_ERROR "Installed Runtime package is missing Bundle break-glass policy example")
endif()
if(NOT EXISTS
        "${prefix}/share/PocoDDSRuntime/examples/project-config-approval-policy.example.json")
    message(FATAL_ERROR
        "Installed Runtime package is missing project configuration approval policy example")
endif()

set(fastdds_profile_example
    "${prefix}/share/PocoDDSRuntime/examples/fastdds-deployment.properties.example")
if(NOT EXISTS "${prefix}/bin/${PDR_FASTDDS_PROFILE_CHECK_FILE_NAME}" OR
        NOT EXISTS "${fastdds_profile_example}")
    message(FATAL_ERROR
        "Installed Runtime package is missing the Fast DDS profile checker or example")
endif()
execute_process(
    COMMAND "${prefix}/bin/${PDR_FASTDDS_PROFILE_CHECK_FILE_NAME}"
            --profile "${fastdds_profile_example}"
    RESULT_VARIABLE fastdds_profile_check_result
    OUTPUT_VARIABLE fastdds_profile_check_output
    ERROR_VARIABLE fastdds_profile_check_error)
if(NOT fastdds_profile_check_result EQUAL 0 OR
        NOT fastdds_profile_check_output MATCHES
            "PDR_FASTDDS_PROFILE_CHECK_PASS configured=true transport=UDPv4")
    message(FATAL_ERROR
        "Installed Fast DDS profile checker failed (${fastdds_profile_check_result})\n"
        "${fastdds_profile_check_output}\n${fastdds_profile_check_error}")
endif()
set(bundle_creator_name "bundle")
if(WIN32)
    set(bundle_creator_name "bundle.exe")
endif()
if(NOT EXISTS "${prefix}/lib/cmake/PocoDDSRuntime/PocoDDSPlugins.cmake" OR
        NOT EXISTS "${prefix}/lib/cmake/PocoDDSRuntime/PocoDDSComponentTesting.cmake" OR
        NOT EXISTS "${prefix}/bin/${bundle_creator_name}" OR
        NOT EXISTS "${prefix}/bin/pdr-plugin-runtime.json")
    message(FATAL_ERROR
        "Installed Runtime package is missing the Plugins CMake API or BundleCreator")
endif()

execute_process(
    COMMAND "${PDR_PYTHON}" "${prefix}/bin/pdr.py"
        component contract-verify --help
    RESULT_VARIABLE component_contract_help_result
    OUTPUT_VARIABLE component_contract_help_output
    ERROR_VARIABLE component_contract_help_error)
if(NOT component_contract_help_result EQUAL 0 OR
        NOT component_contract_help_output MATCHES "verify_report")
    message(FATAL_ERROR
        "Installed component contract evidence CLI is unavailable "
        "(${component_contract_help_result})\n"
        "${component_contract_help_output}\n${component_contract_help_error}")
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
    "${doctor_output}${persistence_help_output}${upgrade_help_output}"
    "${fastdds_profile_check_output}${config_check_output}${smoke_output}")
