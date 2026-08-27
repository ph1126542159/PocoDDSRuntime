if(NOT PDR_CONFIG)
    set(PDR_CONFIG Release)
endif()
if(NOT PDR_DEPENDENCY_PREFIX)
    set(PDR_DEPENDENCY_PREFIX "${PDR_BINARY_DIR}/install")
endif()
find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)

set(install_dir "${PDR_BINARY_DIR}/sdk-consumer-install")
set(consumer_build_dir "${PDR_BINARY_DIR}/sdk-consumer-build")
set(foundation_build_dir "${PDR_BINARY_DIR}/sdk-foundation-consumer-build")
set(unknown_build_dir "${PDR_BINARY_DIR}/sdk-unknown-component-build")
set(transport_build_dir "${PDR_BINARY_DIR}/transport-consumer-build")
set(fastdds_abi_c_build_dir "${PDR_BINARY_DIR}/fastdds-abi-c-consumer-build")
set(workflow_build_dir "${PDR_BINARY_DIR}/workflow-consumer-build")
set(component_contract_build_dir
    "${PDR_BINARY_DIR}/component-contract-consumer-build")
set(consumer_prefix_path "${install_dir}\\;${PDR_DEPENDENCY_PREFIX}")

execute_process(
    COMMAND "${CMAKE_COMMAND}" --install "${PDR_BINARY_DIR}"
        --config "${PDR_CONFIG}" --prefix "${install_dir}"
    RESULT_VARIABLE install_result)
if(NOT install_result EQUAL 0)
    message(FATAL_ERROR "SDK install failed: ${install_result}")
endif()

set(pdr_sdk_executable_suffix "")
if(WIN32)
    set(pdr_sdk_executable_suffix ".exe")
endif()
foreach(required_bundle_supply_chain_artifact
        "${install_dir}/bin/bundle_repository_publisher.py"
        "${install_dir}/bin/bundle_repository_recovery.py"
        "${install_dir}/bin/bundle_repository_break_glass.py"
        "${install_dir}/bin/framework_change_impact.py"
        "${install_dir}/bin/framework_dependency_boundary.py"
        "${install_dir}/bin/framework_link_dependency_boundary.py"
        "${install_dir}/bin/framework_component_build_groups.py"
        "${install_dir}/bin/framework_build_evidence.py"
        "${install_dir}/bin/framework_recovery_matrix.py"
        "${install_dir}/bin/component_contract_test.py"
        "${install_dir}/bin/configuration_participant_contract.py"
        "${install_dir}/bin/configuration_key_lifecycle.py"
        "${install_dir}/bin/service_contract_graph.py"
        "${install_dir}/bin/team_contract_package.py"
        "${install_dir}/bin/team_contract_impact.py"
        "${install_dir}/bin/team_contract_impact_gate.py"
        "${install_dir}/bin/team_contract_registry.py"
        "${install_dir}/bin/team_contract_provenance.py"
        "${install_dir}/bin/team_contract_registry_remote.py"
        "${install_dir}/bin/team_contract_registry_audit_archive.py"
        "${install_dir}/bin/team_contract_registry_recovery.py"
        "${install_dir}/bin/team_contract_registry_standby.py"
        "${install_dir}/bin/team_contract_registry_leader.py"
        "${install_dir}/bin/team_contract_registry_leader_backend.py"
        "${install_dir}/bin/team_contract_registry_leader_backend_capabilities.py"
        "${install_dir}/bin/team_contract_registry_leader_backend_conformance.py"
        "${install_dir}/bin/team_contract_registry_leader_backend_migration.py"
        "${install_dir}/bin/team_contract_artifact_store.py"
        "${install_dir}/bin/team_contract_backend_config_resolver.py"
        "${install_dir}/bin/team_contract_adapter_config_resolver.py"
        "${install_dir}/bin/team_contract_adapter_conformance.py"
        "${install_dir}/bin/team_contract_adapter_conformance_admission.py"
        "${install_dir}/bin/team_contract_adapter_conformance_trust.py"
        "${install_dir}/bin/team_contract_adapter_certifier_signer.py"
        "${install_dir}/bin/team_contract_adapter_certifier_trust_control.py"
        "${install_dir}/bin/team_contract_adapter_certifier_trust_state_store.py"
        "${install_dir}/bin/team_contract_governance_approval.py"
        "${install_dir}/bin/team_contract_governance_approval_signer.py"
        "${install_dir}/bin/team_contract_governance_approval_signer_admission.py"
        "${install_dir}/bin/team_contract_secret_provider.py"
        "${install_dir}/bin/team_contract_adapter_runtime.py"
        "${install_dir}/bin/team_contract_adapter_catalog.py"
        "${install_dir}/bin/team_contract_adapter_catalog_state.py"
        "${install_dir}/bin/team_contract_adapter_catalog_reconciler.py"
        "${install_dir}/bin/team_contract_adapter_catalog_fleet.py"
        "${install_dir}/bin/team_contract_adapter_catalog_fleet_state_store.py"
        "${install_dir}/bin/team_contract_adapter_catalog_wave_gate.py"
        "${install_dir}/bin/team_contract_adapter_catalog_control_authorizer.py"
        "${install_dir}/bin/team_contract_registry_leader_etcd_acceptance.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-file/file_backend_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-file/create_backend_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-file/README.md"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl/etcd_backend_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl/create_backend_configs.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl/etcd_cluster_preflight.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl/README.md"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-artifact-store-file/file_artifact_store_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-artifact-store-file/create_artifact_store_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-artifact-store-file/README.md"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-artifact-store-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-artifact-reference.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-artifact-store-capability-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-artifact-store-capability-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-artifact-store-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-artifact-store-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-backend-config-resolver-file/file_backend_config_resolver_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-backend-config-resolver-file/create_resolver_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-backend-config-resolver-file/README.md"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-config-resolver-file/file_adapter_config_resolver_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-config-resolver-file/create_resolver_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-config-resolver-file/README.md"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-secret-provider-environment/environment_secret_provider_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-secret-provider-environment/create_secret_provider_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-secret-provider-environment/README.md"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-certifier-signer-local/local_ed25519_certifier_signer_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-certifier-signer-local/create_signer_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-certifier-signer-local/README.md"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-governance-approval-signer-local/local_ed25519_governance_approval_signer_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-governance-approval-signer-local/create_signer_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-governance-approval-signer-local/README.md"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/create_adapter_manifest.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/create_adapter_catalog.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/create_reconciler_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/lifecycle_reconciler_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/create_fleet_node_map.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/create_fleet_executor_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/create_fleet_plan.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/create_conformance_trust_demo.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/fleet_node_executor_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/create_wave_gate_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/wave_gate_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/create_control_authorizer_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/control_authorizer_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog/README.md"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-backend-config-reference.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-backend-config-resolver-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-backend-config-resolver-capability-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-backend-config-resolver-capability-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-backend-config-resolver-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-backend-config-resolver-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-config-reference.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-config-resolver-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-config-resolver-capability-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-config-resolver-capability-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-config-resolver-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-config-resolver-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-conformance-evidence.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-conformance-admission-bundle.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-conformance-attestation.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-trust-governance.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-trust-proposal.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-trust-approval.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-trust-activation.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-trust-state-pointer.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-trust-state.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-trust-state-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-trust-migration-preflight.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-trust-migration-proposal.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-trust-migration-approval.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-trust-migration-report.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-subject.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-signature.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-evidence.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-signer-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-signer-capability-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-signer-capability-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-signer-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-signer-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-signing-payload.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-signer-admission-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-signer-readmission-bundle.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-governance-approval-signer-readmission-evidence.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-conformance-trust-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-signer-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-signer-capability-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-signer-capability-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-signer-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-certifier-signer-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-secret-reference.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-secret-provider-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-secret-provider-capability-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-secret-provider-capability-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-secret-provider-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-secret-provider-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-secret-provider-check.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-listing.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-check.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-pointer.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-state.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-state-operation.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-current.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-current-check.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-state-verification.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-reconciler-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-reconciler-capability-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-reconciler-capability-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-reconciler-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-reconciler-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-reconcile-journal.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-reconcile-report.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-reconcile-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-fleet-plan.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-fleet-executor-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-fleet-executor-capability-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-fleet-executor-capability-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-fleet-executor-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-fleet-executor-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-fleet-node-map.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-fleet-journal.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-fleet-report.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-fleet-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-fleet-state-pointer.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-wave-gate-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-wave-gate-capability-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-wave-gate-capability-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-wave-gate-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-wave-gate-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-control-authorizer-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-control-authorizer-capability-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-control-authorizer-capability-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-control-authorizer-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-adapter-catalog-control-authorizer-response.schema.json"
        "${install_dir}/bin/team_contract_registry_handoff.py"
        "${install_dir}/bin/team_contract_registry_access_policy.py"
        "${install_dir}/bin/process_file_lease.py"
        "${install_dir}/bin/project_config_approval.py"
        "${install_dir}/bin/project_config_audit.py"
        "${install_dir}/bin/project_config_audit_checkpoint.py"
        "${install_dir}/bin/project_config_status.py"
        "${install_dir}/lib/cmake/PocoDDSRuntime/PocoDDSComponentTesting.cmake"
        "${install_dir}/bin/sdk_surface_guard.py"
        "${install_dir}/bin/sdk_deprecation_guard.py"
        "${install_dir}/bin/sdk_header_self_containment.py"
        "${install_dir}/bin/repository_ownership.py"
        "${install_dir}/bin/pdr-bundle-repository-check${pdr_sdk_executable_suffix}"
        "${install_dir}/bin/pdr-signature-check${pdr_sdk_executable_suffix}"
        "${install_dir}/include/PocoDDS/BundleManagement/BundleRepositoryAuthorization.h"
        "${install_dir}/include/PocoDDS/BundleManagement/BundleRepositoryRolloutGuard.h"
        "${install_dir}/include/PocoDDS/Security/DetachedSignatureVerifier.h"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/bundle-repository-attestation.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/bundle-repository-trust-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/bundle-repository-break-glass-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/bundle-repository-break-glass-trust-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/bundle-repository-break-glass-audit.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/bundle-repository-break-glass-preflight.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/bundle-repository-break-glass-transaction.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/bundle-repository-break-glass-recovery.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/project-config-approval-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/project-config-approval-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/project-config-approval-signature.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/project-config-audit-record.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/project-config-audit-head.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/project-config-audit-verification.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/project-config-audit-checkpoint.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/project-config-audit-checkpoint-signature.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/project-config-audit-checkpoint-verification.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/project-config-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/project-config-preflight.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/service-contract-baseline.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/service-contract-graph.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/service-contract-baseline.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/configuration-participants.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/configuration-participant-contract-report.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/configuration-participant-baseline.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/configuration-participant-baseline.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/configuration-key-lifecycle.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/configuration-key-lifecycle-contract-report.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/configuration-key-lifecycle-baseline.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/configuration-key-lifecycle-baseline.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-package-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-package-lock.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-package-resolution.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-package-signature.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-trust-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-consumer-catalog.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-upgrade-impact.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-impact-execution-evidence.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-impact-approval-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-impact-approval.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-impact-gate.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-pointer.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-state.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-operation.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-resolution.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-runner-trust-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-runner-attestation.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-runner-attestation-verification.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-gate-authorization-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-gate-authorization.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-gate-authorization-verification.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-access-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-access-policy-v2.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-access-policy-trust-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-access-policy-activation.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-command.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-capacity.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/process-file-lease-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-lease-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-request-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-recovery.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-recovery-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-head.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-activation.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-record.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-verification.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-checkpoint.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-checkpoint-verification.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-archive-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-archive-marker.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-archive-base.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-archive-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-audit-archive-report.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-recovery-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-recovery-report.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-standby-marker.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-standby-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-standby-report.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-grant.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-capability-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-capability-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-capability-report.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-conformance.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-migration-sync.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-migration.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-migration-transaction.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-migration-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-migration-abort.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-etcd-adapter-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-etcd-preflight.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-etcd-acceptance.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-trust-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-binding.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-activation.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-fencing-state.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-drain-state.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-drain-status.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-handoff-evidence.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-handoff-trust-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-drain-command.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-remote-drain-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-anchor-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-anchor.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-anchor-verification.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-components.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-dependency-boundary.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-link-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-link-dependency-boundary.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-link-dependency-matrix.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-component-build-groups.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-component-build-groups-validation.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-build-execution-evidence.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-change-impact.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-ci-execution-evidence.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-recovery-matrix.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/framework-recovery-evidence.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/component-contract-conformance.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/sdk-public-surface-snapshot.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/sdk-public-surface-compatibility.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/sdk-deprecation-catalog.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/sdk-deprecation-policy.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/sdk-header-self-containment-plan.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/sdk-header-self-containment-evidence.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/repository-owners.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/release-artifact-manifest.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/compatibility/sdk-surface-0.1.0.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/sdk-deprecations.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/repository-owners.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/framework-components.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/framework-recovery-matrix.json")
    if(NOT EXISTS "${required_bundle_supply_chain_artifact}")
        message(FATAL_ERROR
            "Installed Bundle supply-chain artifact is missing: ${required_bundle_supply_chain_artifact}")
    endif()
endforeach()

# Adapter teams must be able to start from the installed SDK alone. Generate a
# digest-pinned config for the installed reference adapter and qualify its real
# byte store/CAS behavior through the installed pdr CLI.
set(leader_backend_example_dir
    "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-file")
set(artifact_store_example_dir
    "${install_dir}/share/PocoDDSRuntime/examples/team-contract-artifact-store-file")
set(config_resolver_example_dir
    "${install_dir}/share/PocoDDSRuntime/examples/team-contract-backend-config-resolver-file")
set(adapter_config_resolver_example_dir
    "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-config-resolver-file")
set(secret_provider_example_dir
    "${install_dir}/share/PocoDDSRuntime/examples/team-contract-secret-provider-environment")
set(certifier_signer_example_dir
    "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-certifier-signer-local")
set(adapter_catalog_example_dir
    "${install_dir}/share/PocoDDSRuntime/examples/team-contract-adapter-catalog")
set(leader_backend_example_work
    "${PDR_BINARY_DIR}/sdk-leader-backend-adapter-example")
set(leader_backend_example_store "${leader_backend_example_work}/store")
set(leader_backend_example_target_store
    "${leader_backend_example_work}/target-store")
set(leader_backend_example_transaction_store
    "${leader_backend_example_work}/transaction-store")
set(leader_backend_example_artifact_store
    "${leader_backend_example_work}/artifact-store")
set(leader_backend_example_artifact_config
    "${leader_backend_example_work}/artifact-store.json")
set(leader_backend_example_resolver_config
    "${leader_backend_example_work}/backend-config-resolver.json")
set(leader_backend_example_resolver_mapping
    "${leader_backend_example_work}/backend-config-resolver-map.json")
set(leader_backend_example_source_ref
    "${leader_backend_example_work}/source-backend-ref.json")
set(leader_backend_example_target_ref
    "${leader_backend_example_work}/target-backend-ref.json")
set(leader_backend_example_config "${leader_backend_example_work}/backend.json")
set(leader_backend_example_target_config
    "${leader_backend_example_work}/target-backend.json")
set(leader_backend_example_capability_report
    "${leader_backend_example_work}/capabilities.json")
set(leader_backend_example_report "${leader_backend_example_work}/conformance.json")
set(leader_backend_example_migration_sync
    "${leader_backend_example_work}/migration-sync.json")
set(leader_backend_example_transaction_config
    "${leader_backend_example_work}/transaction-backend.json")
set(leader_backend_example_migration_resume
    "${leader_backend_example_work}/migration-resume.json")
file(REMOVE_RECURSE "${leader_backend_example_work}")
file(MAKE_DIRECTORY "${leader_backend_example_store}"
    "${leader_backend_example_target_store}"
    "${leader_backend_example_transaction_store}"
    "${leader_backend_example_artifact_store}")
set(secret_provider_config "${leader_backend_example_work}/secret-provider.json")
set(secret_provider_mapping "${leader_backend_example_work}/secret-map.json")
set(secret_provider_reference "${leader_backend_example_work}/secret-ref.json")
set(secret_provider_report "${leader_backend_example_work}/secret-check.json")
set(adapter_manifest "${leader_backend_example_work}/secret-adapter-manifest.json")
set(adapter_catalog "${leader_backend_example_work}/adapter-catalog.json")
set(adapter_catalog_listing "${leader_backend_example_work}/adapter-listing.json")
set(adapter_catalog_check "${leader_backend_example_work}/adapter-check.json")
set(adapter_catalog_state_dir
    "${leader_backend_example_work}/adapter-catalog-state")
set(adapter_catalog_activation
    "${leader_backend_example_work}/adapter-catalog-activation.json")
set(adapter_catalog_current_check
    "${leader_backend_example_work}/adapter-catalog-current-check.json")
set(adapter_catalog_state_verification
    "${leader_backend_example_work}/adapter-catalog-state-verification.json")
set(adapter_catalog_candidate
    "${leader_backend_example_work}/adapter-catalog-generation-2.json")
set(adapter_catalog_reconciler_config
    "${leader_backend_example_work}/adapter-catalog-reconciler.json")
set(adapter_catalog_reconcile_state
    "${leader_backend_example_work}/adapter-catalog-reconcile-state")
set(adapter_catalog_lifecycle_state
    "${leader_backend_example_work}/adapter-catalog-lifecycle-state")
set(adapter_catalog_reconcile_report
    "${leader_backend_example_work}/adapter-catalog-reconcile.json")
set(adapter_catalog_reconcile_status
    "${leader_backend_example_work}/adapter-catalog-reconcile-status.json")
set(adapter_catalog_reconcile_revert
    "${leader_backend_example_work}/adapter-catalog-reconcile-revert.json")
set(adapter_catalog_fleet_node_a_state
    "${leader_backend_example_work}/fleet-node-a-state")
set(adapter_catalog_fleet_node_b_state
    "${leader_backend_example_work}/fleet-node-b-state")
set(adapter_catalog_fleet_node_map
    "${leader_backend_example_work}/fleet-node-map.json")
set(adapter_catalog_fleet_executor_config
    "${leader_backend_example_work}/fleet-executor.json")
set(adapter_catalog_fleet_gate_config
    "${leader_backend_example_work}/fleet-wave-gate.json")
set(adapter_catalog_fleet_gate_state
    "${leader_backend_example_work}/fleet-wave-gate-state")
set(adapter_catalog_fleet_authorizer_config
    "${leader_backend_example_work}/fleet-control-authorizer.json")
set(adapter_catalog_fleet_authorizer_state
    "${leader_backend_example_work}/fleet-control-authorizer-state")
set(adapter_catalog_fleet_plan
    "${leader_backend_example_work}/fleet-plan.json")
set(adapter_catalog_fleet_state
    "${leader_backend_example_work}/fleet-state")
set(adapter_catalog_fleet_takeover_state
    "${leader_backend_example_work}/fleet-takeover-state")
set(adapter_catalog_fleet_state_backend_store
    "${leader_backend_example_work}/fleet-state-backend-store")
set(adapter_catalog_fleet_state_backend_config
    "${leader_backend_example_work}/fleet-state-backend.json")
set(adapter_catalog_fleet_artifact_store
    "${leader_backend_example_work}/fleet-journal-artifacts")
set(adapter_catalog_fleet_artifact_config
    "${leader_backend_example_work}/fleet-journal-store.json")
set(adapter_catalog_fleet_resolver_mapping_a
    "${leader_backend_example_work}/fleet-resolver-host-a-mapping.json")
set(adapter_catalog_fleet_resolver_config_a
    "${leader_backend_example_work}/fleet-resolver-host-a.json")
set(adapter_catalog_fleet_resolver_mapping_b
    "${leader_backend_example_work}/fleet-resolver-host-b-mapping.json")
set(adapter_catalog_fleet_resolver_config_b
    "${leader_backend_example_work}/fleet-resolver-host-b.json")
set(adapter_catalog_fleet_admission_bundle_a
    "${leader_backend_example_work}/fleet-admission-host-a.json")
set(adapter_catalog_fleet_admission_bundle_b
    "${leader_backend_example_work}/fleet-admission-host-b.json")
set(adapter_catalog_fleet_trust_dir
    "${leader_backend_example_work}/fleet-conformance-trust")
set(adapter_catalog_fleet_trust_policy
    "${adapter_catalog_fleet_trust_dir}/policy.json")
set(adapter_catalog_fleet_trust_private_key
    "${leader_backend_example_work}/fleet-conformance-certifier-private.pem")
set(adapter_catalog_fleet_trust_public_key
    "${adapter_catalog_fleet_trust_dir}/keys/certifier-a.pem")
set(adapter_catalog_fleet_signer_mapping
    "${leader_backend_example_work}/fleet-certifier-signer-mapping.json")
set(adapter_catalog_fleet_signer_config
    "${leader_backend_example_work}/fleet-certifier-signer.json")
set(adapter_catalog_fleet_attestation_executor
    "${leader_backend_example_work}/attestation-fleet-executor.json")
set(adapter_catalog_fleet_attestation_gate
    "${leader_backend_example_work}/attestation-wave-gate.json")
set(adapter_catalog_fleet_attestation_authorizer
    "${leader_backend_example_work}/attestation-control-authorizer.json")
set(adapter_catalog_fleet_attestation_state
    "${leader_backend_example_work}/attestation-state-backend.json")
set(adapter_catalog_fleet_attestation_artifact
    "${leader_backend_example_work}/attestation-artifact-store.json")
set(adapter_catalog_fleet_attestation_resolver_a
    "${leader_backend_example_work}/attestation-resolver-host-a.json")
set(adapter_catalog_fleet_attestation_resolver_b
    "${leader_backend_example_work}/attestation-resolver-host-b.json")
set(adapter_catalog_fleet_report
    "${leader_backend_example_work}/fleet-report.json")
set(secret_rotation_backend_store
    "${leader_backend_example_work}/secret-rotation-backend-store")
set(secret_rotation_backend_config
    "${leader_backend_example_work}/secret-rotation-backend.json")
set(secret_rotation_backend_report
    "${leader_backend_example_work}/secret-rotation-conformance.json")
file(MAKE_DIRECTORY "${secret_rotation_backend_store}"
    "${adapter_catalog_fleet_state_backend_store}"
    "${adapter_catalog_fleet_artifact_store}")
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${secret_provider_example_dir}/create_secret_provider_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter "${secret_provider_example_dir}/environment_secret_provider_adapter.py"
        --provider-id installed-sdk-secret-provider
        --entry backend-auth deploy-2026-09 PDR_INSTALLED_SDK_SECRET_NEW
        --entry backend-auth deploy-2026-08 PDR_INSTALLED_SDK_SECRET_OLD
        --mapping-output "${secret_provider_mapping}"
        --output "${secret_provider_config}"
    RESULT_VARIABLE secret_provider_config_result
    OUTPUT_VARIABLE secret_provider_config_output
    ERROR_VARIABLE secret_provider_config_error)
if(NOT secret_provider_config_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Secret Provider config generation failed: "
        "${secret_provider_config_result}\n${secret_provider_config_output}\n"
        "${secret_provider_config_error}")
endif()
file(WRITE "${secret_provider_reference}"
    "{\"kind\":\"secret-rotation-ref\",\"providerId\":\"installed-sdk-secret-provider\",\"secretId\":\"backend-auth\",\"versions\":[\"deploy-2026-09\",\"deploy-2026-08\"],\"fallbackUntil\":\"2099-01-01T00:00:00+00:00\"}\n")
file(SHA256 "${secret_provider_config}" secret_provider_config_sha256)
file(SHA256 "${secret_provider_reference}" secret_provider_reference_sha256)
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        PDR_INSTALLED_SDK_SECRET_OLD=pdr-installed-sdk-secret-never-persisted
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package secret-provider-check
        --config "${secret_provider_config}"
        --expected-config-sha256 "${secret_provider_config_sha256}"
        --reference "${secret_provider_reference}"
        --expected-reference-sha256 "${secret_provider_reference_sha256}"
        --report "${secret_provider_report}"
    RESULT_VARIABLE secret_provider_check_result
    OUTPUT_VARIABLE secret_provider_check_output
    ERROR_VARIABLE secret_provider_check_error)
if(NOT secret_provider_check_result EQUAL 0
        OR NOT secret_provider_check_output MATCHES
            "PDR_SECRET_PROVIDER_CHECK_PASS")
    message(FATAL_ERROR
        "Installed Secret Provider check failed: ${secret_provider_check_result}\n"
        "${secret_provider_check_output}\n${secret_provider_check_error}")
endif()
file(READ "${secret_provider_report}" secret_provider_report_content)
if(secret_provider_report_content MATCHES
        "pdr-installed-sdk-secret-never-persisted|secretBase64")
    message(FATAL_ERROR
        "Installed Secret Provider report disclosed secret material")
endif()
if(NOT secret_provider_report_content MATCHES
        "\"selectedVersion\"[ \t\r\n]*:[ \t\r\n]*\"deploy-2026-08\"")
    message(FATAL_ERROR
        "Installed Secret Provider did not exercise the bounded fallback")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${adapter_catalog_example_dir}/create_adapter_manifest.py"
        --config "${secret_provider_config}"
        --manifest-id installed-sdk-secret-provider.deploy-2026-09
        --adapter-id installed-sdk-secret-provider
        --adapter-type secret-provider
        --owner team/runtime-governance
        --revision deploy-2026-09 --protocol-id pdr.secret-provider
        --identity-field providerId
        --capability-request-product
            PocoDDSRuntimeTeamContractSecretProviderCapabilityRequest
        --capability-manifest-product
            PocoDDSRuntimeTeamContractSecretProviderCapabilityManifest
        --output "${adapter_manifest}"
    RESULT_VARIABLE adapter_manifest_result
    OUTPUT_VARIABLE adapter_manifest_output
    ERROR_VARIABLE adapter_manifest_error)
if(NOT adapter_manifest_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Adapter Manifest generation failed: ${adapter_manifest_result}\n"
        "${adapter_manifest_output}\n${adapter_manifest_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${adapter_catalog_example_dir}/create_adapter_catalog.py"
        --catalog-id installed-sdk-adapters --generation 1
        --manifest "${adapter_manifest}" --output "${adapter_catalog}"
    RESULT_VARIABLE adapter_catalog_result
    OUTPUT_VARIABLE adapter_catalog_output
    ERROR_VARIABLE adapter_catalog_error)
if(NOT adapter_catalog_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Adapter Catalog generation failed: ${adapter_catalog_result}\n"
        "${adapter_catalog_output}\n${adapter_catalog_error}")
endif()
file(SHA256 "${adapter_catalog}" adapter_catalog_sha256)
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${adapter_catalog_example_dir}/create_adapter_catalog.py"
        --catalog-id installed-sdk-adapters --generation 2
        --manifest "${adapter_manifest}" --output "${adapter_catalog_candidate}"
    RESULT_VARIABLE adapter_catalog_candidate_result
    OUTPUT_VARIABLE adapter_catalog_candidate_output
    ERROR_VARIABLE adapter_catalog_candidate_error)
if(NOT adapter_catalog_candidate_result EQUAL 0)
    message(FATAL_ERROR
        "Installed candidate Adapter Catalog generation failed: "
        "${adapter_catalog_candidate_result}\n${adapter_catalog_candidate_output}\n"
        "${adapter_catalog_candidate_error}")
endif()
file(SHA256 "${adapter_catalog_candidate}"
    adapter_catalog_candidate_sha256)
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${adapter_catalog_example_dir}/create_reconciler_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter
            "${adapter_catalog_example_dir}/lifecycle_reconciler_adapter.py"
        --reconciler-id installed-sdk-catalog-reconciler
        --optional-environment PDR_RECONCILER_SECRET_SENTINEL
        --output "${adapter_catalog_reconciler_config}"
    RESULT_VARIABLE adapter_catalog_reconciler_config_result
    OUTPUT_VARIABLE adapter_catalog_reconciler_config_output
    ERROR_VARIABLE adapter_catalog_reconciler_config_error)
if(NOT adapter_catalog_reconciler_config_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Adapter Catalog Reconciler config generation failed: "
        "${adapter_catalog_reconciler_config_result}\n"
        "${adapter_catalog_reconciler_config_output}\n"
        "${adapter_catalog_reconciler_config_error}")
endif()
file(SHA256 "${adapter_catalog_reconciler_config}"
    adapter_catalog_reconciler_config_sha256)
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package adapter-catalog-list
        --catalog "${adapter_catalog}"
        --expected-catalog-sha256 "${adapter_catalog_sha256}"
        --report "${adapter_catalog_listing}"
    RESULT_VARIABLE adapter_catalog_list_result
    OUTPUT_VARIABLE adapter_catalog_list_output
    ERROR_VARIABLE adapter_catalog_list_error)
if(NOT adapter_catalog_list_result EQUAL 0 OR
        NOT adapter_catalog_list_output MATCHES "PDR_ADAPTER_CATALOG_LIST_PASS")
    message(FATAL_ERROR
        "Installed Adapter Catalog listing failed: ${adapter_catalog_list_result}\n"
        "${adapter_catalog_list_output}\n${adapter_catalog_list_error}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        PDR_INSTALLED_SDK_SECRET_OLD=pdr-installed-sdk-secret-never-persisted
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package adapter-catalog-check
        --catalog "${adapter_catalog}"
        --expected-catalog-sha256 "${adapter_catalog_sha256}"
        --report "${adapter_catalog_check}"
    RESULT_VARIABLE adapter_catalog_check_result
    OUTPUT_VARIABLE adapter_catalog_check_output
    ERROR_VARIABLE adapter_catalog_check_error)
if(NOT adapter_catalog_check_result EQUAL 0 OR
        NOT adapter_catalog_check_output MATCHES "PDR_ADAPTER_CATALOG_CHECK_PASS")
    message(FATAL_ERROR
        "Installed Adapter Catalog check failed: ${adapter_catalog_check_result}\n"
        "${adapter_catalog_check_output}\n${adapter_catalog_check_error}")
endif()
file(READ "${adapter_catalog_check}" adapter_catalog_check_content)
if(adapter_catalog_check_content MATCHES
        "pdr-installed-sdk-secret-never-persisted|secretBase64")
    message(FATAL_ERROR "Installed Adapter Catalog report disclosed secret material")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package adapter-catalog-activate
        --catalog "${adapter_catalog}"
        --expected-catalog-sha256 "${adapter_catalog_sha256}"
        --state-dir "${adapter_catalog_state_dir}"
        --expected-generation 0
        --operation-id installed-sdk-catalog-activate
        --actor sdk-consumer
        --reason "qualify installed Adapter Catalog state"
        --report "${adapter_catalog_activation}"
    RESULT_VARIABLE adapter_catalog_activate_result
    OUTPUT_VARIABLE adapter_catalog_activate_output
    ERROR_VARIABLE adapter_catalog_activate_error)
if(NOT adapter_catalog_activate_result EQUAL 0 OR
        NOT adapter_catalog_activate_output MATCHES
            "PDR_ADAPTER_CATALOG_ACTIVATE_PASS")
    message(FATAL_ERROR
        "Installed Adapter Catalog activation failed: "
        "${adapter_catalog_activate_result}\n${adapter_catalog_activate_output}\n"
        "${adapter_catalog_activate_error}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        PDR_INSTALLED_SDK_SECRET_OLD=pdr-installed-sdk-secret-never-persisted
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package adapter-catalog-current-check
        --state-dir "${adapter_catalog_state_dir}"
        --report "${adapter_catalog_current_check}"
    RESULT_VARIABLE adapter_catalog_current_result
    OUTPUT_VARIABLE adapter_catalog_current_output
    ERROR_VARIABLE adapter_catalog_current_error)
if(NOT adapter_catalog_current_result EQUAL 0 OR
        NOT adapter_catalog_current_output MATCHES
            "PDR_ADAPTER_CATALOG_CURRENT_CHECK_PASS")
    message(FATAL_ERROR
        "Installed current Adapter Catalog check failed: "
        "${adapter_catalog_current_result}\n${adapter_catalog_current_output}\n"
        "${adapter_catalog_current_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package adapter-catalog-state-verify
        --state-dir "${adapter_catalog_state_dir}"
        --report "${adapter_catalog_state_verification}"
    RESULT_VARIABLE adapter_catalog_state_verify_result
    OUTPUT_VARIABLE adapter_catalog_state_verify_output
    ERROR_VARIABLE adapter_catalog_state_verify_error)
if(NOT adapter_catalog_state_verify_result EQUAL 0 OR
        NOT adapter_catalog_state_verify_output MATCHES
            "PDR_ADAPTER_CATALOG_STATE_VERIFY_PASS")
    message(FATAL_ERROR
        "Installed Adapter Catalog state verification failed: "
        "${adapter_catalog_state_verify_result}\n"
        "${adapter_catalog_state_verify_output}\n"
        "${adapter_catalog_state_verify_error}")
endif()
file(READ "${adapter_catalog_current_check}"
    adapter_catalog_current_check_content)
if(adapter_catalog_current_check_content MATCHES
        "pdr-installed-sdk-secret-never-persisted|secretBase64")
    message(FATAL_ERROR
        "Installed current Adapter Catalog report disclosed secret material")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_RECONCILER_STATE_ROOT=${adapter_catalog_lifecycle_state}"
        PDR_RECONCILER_SECRET_SENTINEL=pdr-installed-reconciler-secret-never-persisted
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package adapter-catalog-reconcile
        --config "${adapter_catalog_reconciler_config}"
        --expected-config-sha256 "${adapter_catalog_reconciler_config_sha256}"
        --state-dir "${adapter_catalog_state_dir}"
        --transaction-dir "${adapter_catalog_reconcile_state}"
        --transaction-id installed-sdk-catalog-rollout-2
        --catalog "${adapter_catalog_candidate}"
        --expected-catalog-sha256 "${adapter_catalog_candidate_sha256}"
        --expected-generation 1 --actor sdk-consumer
        --reason "qualify installed health-gated Catalog rollout"
        --report "${adapter_catalog_reconcile_report}"
    RESULT_VARIABLE adapter_catalog_reconcile_result
    OUTPUT_VARIABLE adapter_catalog_reconcile_output
    ERROR_VARIABLE adapter_catalog_reconcile_error)
if(NOT adapter_catalog_reconcile_result EQUAL 0 OR
        NOT adapter_catalog_reconcile_output MATCHES
            "PDR_ADAPTER_CATALOG_RECONCILE_PASS")
    message(FATAL_ERROR
        "Installed Adapter Catalog reconcile failed: "
        "${adapter_catalog_reconcile_result}\n${adapter_catalog_reconcile_output}\n"
        "${adapter_catalog_reconcile_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package adapter-catalog-reconcile-status
        --transaction-dir "${adapter_catalog_reconcile_state}"
        --transaction-id installed-sdk-catalog-rollout-2
        --report "${adapter_catalog_reconcile_status}"
    RESULT_VARIABLE adapter_catalog_reconcile_status_result
    OUTPUT_VARIABLE adapter_catalog_reconcile_status_output
    ERROR_VARIABLE adapter_catalog_reconcile_status_error)
if(NOT adapter_catalog_reconcile_status_result EQUAL 0 OR
        NOT adapter_catalog_reconcile_status_output MATCHES
            "PDR_ADAPTER_CATALOG_RECONCILE_STATUS_PASS")
    message(FATAL_ERROR
        "Installed Adapter Catalog reconcile status failed: "
        "${adapter_catalog_reconcile_status_result}\n"
        "${adapter_catalog_reconcile_status_output}\n"
        "${adapter_catalog_reconcile_status_error}")
endif()
file(READ "${adapter_catalog_reconcile_report}"
    adapter_catalog_reconcile_report_content)
file(READ "${adapter_catalog_reconcile_status}"
    adapter_catalog_reconcile_status_content)
if(adapter_catalog_reconcile_report_content MATCHES
        "pdr-installed-reconciler-secret-never-persisted|secretBase64" OR
        adapter_catalog_reconcile_status_content MATCHES
        "pdr-installed-reconciler-secret-never-persisted|secretBase64" OR
        NOT adapter_catalog_reconcile_report_content MATCHES
        "\"status\"[ \t\r\n]*:[ \t\r\n]*\"committed\"" OR
        NOT adapter_catalog_reconcile_status_content MATCHES
        "\"terminal\"[ \t\r\n]*:[ \t\r\n]*true")
    message(FATAL_ERROR
        "Installed Adapter Catalog reconcile evidence is unsafe or incomplete")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_RECONCILER_STATE_ROOT=${adapter_catalog_lifecycle_state}"
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package adapter-catalog-reconcile-revert
        --config "${adapter_catalog_reconciler_config}"
        --expected-config-sha256 "${adapter_catalog_reconciler_config_sha256}"
        --state-dir "${adapter_catalog_state_dir}"
        --transaction-dir "${adapter_catalog_reconcile_state}"
        --transaction-id installed-sdk-catalog-rollout-2
        --report "${adapter_catalog_reconcile_revert}"
    RESULT_VARIABLE adapter_catalog_reconcile_revert_result
    OUTPUT_VARIABLE adapter_catalog_reconcile_revert_output
    ERROR_VARIABLE adapter_catalog_reconcile_revert_error)
if(NOT adapter_catalog_reconcile_revert_result EQUAL 0 OR
        NOT adapter_catalog_reconcile_revert_output MATCHES
            "PDR_ADAPTER_CATALOG_RECONCILE_REVERT_PASS")
    message(FATAL_ERROR
        "Installed Adapter Catalog reconcile revert failed: "
        "${adapter_catalog_reconcile_revert_result}\n"
        "${adapter_catalog_reconcile_revert_output}\n"
        "${adapter_catalog_reconcile_revert_error}")
endif()
file(READ "${adapter_catalog_reconcile_revert}"
    adapter_catalog_reconcile_revert_content)
if(NOT adapter_catalog_reconcile_revert_content MATCHES
        "\"status\"[ \t\r\n]*:[ \t\r\n]*\"rolled-back\"" OR
        NOT adapter_catalog_reconcile_revert_content MATCHES
        "\"rollbackGeneration\"[ \t\r\n]*:[ \t\r\n]*3")
    message(FATAL_ERROR
        "Installed Adapter Catalog explicit revert evidence is incomplete")
endif()
foreach(fleet_node IN ITEMS a b)
    execute_process(
        COMMAND "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
            contract-package adapter-catalog-activate
            --catalog "${adapter_catalog}"
            --expected-catalog-sha256 "${adapter_catalog_sha256}"
            --state-dir
                "${leader_backend_example_work}/fleet-node-${fleet_node}-state"
            --expected-generation 0
            --operation-id "installed-fleet-bootstrap-${fleet_node}"
            --actor sdk-consumer --reason "bootstrap installed Fleet node"
        RESULT_VARIABLE adapter_catalog_fleet_bootstrap_result
        OUTPUT_VARIABLE adapter_catalog_fleet_bootstrap_output
        ERROR_VARIABLE adapter_catalog_fleet_bootstrap_error)
    if(NOT adapter_catalog_fleet_bootstrap_result EQUAL 0 OR
            NOT adapter_catalog_fleet_bootstrap_output MATCHES
                "PDR_ADAPTER_CATALOG_ACTIVATE_PASS")
        message(FATAL_ERROR
            "Installed Fleet node bootstrap failed: ${fleet_node} "
            "${adapter_catalog_fleet_bootstrap_result}\n"
            "${adapter_catalog_fleet_bootstrap_output}\n"
            "${adapter_catalog_fleet_bootstrap_error}")
    endif()
endforeach()
function(pdr_run_installed_adapter_conformance adapter_kind config_path report_path)
    file(SHA256 "${config_path}" adapter_conformance_config_sha256)
    execute_process(
        COMMAND "${CMAKE_COMMAND}" -E env
            "PDR_WAVE_GATE_STATE_ROOT=${adapter_catalog_fleet_gate_state}"
            "PDR_CONTROL_AUTHORIZER_STATE_ROOT=${adapter_catalog_fleet_authorizer_state}"
            "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
            contract-package adapter-conformance
            --adapter-kind "${adapter_kind}"
            --config "${config_path}"
            --expected-config-sha256
                "${adapter_conformance_config_sha256}"
            --report "${report_path}" ${ARGN}
        RESULT_VARIABLE adapter_conformance_result
        OUTPUT_VARIABLE adapter_conformance_output
        ERROR_VARIABLE adapter_conformance_error)
    if(NOT adapter_conformance_result EQUAL 0 OR
            NOT adapter_conformance_output MATCHES
                "PDR_ADAPTER_CONFORMANCE_PASS")
        message(FATAL_ERROR
            "Installed Adapter conformance failed for ${adapter_kind}: "
            "${adapter_conformance_result}\n${adapter_conformance_output}\n"
            "${adapter_conformance_error}")
    endif()
    file(READ "${report_path}" adapter_conformance_report_content)
    if(NOT adapter_conformance_report_content MATCHES
            "PocoDDSRuntimeTeamContractAdapterConformanceEvidence" OR
            NOT adapter_conformance_report_content MATCHES
            "\"certificationLevel\"[ \t\r\n]*:[ \t\r\n]*\"integration-readiness\"" OR
            NOT adapter_conformance_report_content MATCHES
            "\"passed\"[ \t\r\n]*:[ \t\r\n]*true" OR
            NOT adapter_conformance_report_content MATCHES
            "\"reportSha256\"[ \t\r\n]*:")
        message(FATAL_ERROR
            "Installed Adapter conformance evidence is incomplete for "
            "${adapter_kind}: ${adapter_conformance_report_content}")
    endif()
endfunction()
function(pdr_attest_installed_adapter_conformance evidence_path report_path)
    file(SHA256 "${evidence_path}" adapter_conformance_evidence_sha256)
    execute_process(
        COMMAND "${CMAKE_COMMAND}" -E env
            "PDR_INSTALLED_ADAPTER_CERTIFIER_KEY=${adapter_catalog_fleet_trust_private_key}"
            "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
            contract-package adapter-conformance-attest
            --evidence "${evidence_path}"
            --expected-evidence-sha256
                "${adapter_conformance_evidence_sha256}"
            --certifier-id installed-sdk-adapter-team
            --key-id installed-sdk-certifier-key-a
            --signer-config "${adapter_catalog_fleet_signer_config}"
            --expected-signer-config-sha256
                "${adapter_catalog_fleet_signer_config_sha256}"
            --lifetime-seconds 3600
            --report "${report_path}"
        RESULT_VARIABLE adapter_attestation_result
        OUTPUT_VARIABLE adapter_attestation_output
        ERROR_VARIABLE adapter_attestation_error)
    if(NOT adapter_attestation_result EQUAL 0 OR
            NOT adapter_attestation_output MATCHES
                "PDR_ADAPTER_CONFORMANCE_ATTEST_PASS")
        message(FATAL_ERROR
            "Installed Adapter conformance attestation failed for "
            "${evidence_path}: ${adapter_attestation_result}\n"
            "${adapter_attestation_output}\n${adapter_attestation_error}")
    endif()
endfunction()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${adapter_catalog_example_dir}/create_fleet_node_map.py"
        --executor-id installed-sdk-fleet
        --audit "${leader_backend_example_work}/fleet-audit.log"
        --node node-a "${adapter_catalog_fleet_node_a_state}"
            "${leader_backend_example_work}/fleet-node-a-transactions"
            "${leader_backend_example_work}/fleet-node-a-lifecycle"
            "${adapter_catalog_reconciler_config}"
            "${adapter_catalog_candidate}" 1 healthy
        --node node-b "${adapter_catalog_fleet_node_b_state}"
            "${leader_backend_example_work}/fleet-node-b-transactions"
            "${leader_backend_example_work}/fleet-node-b-lifecycle"
            "${adapter_catalog_reconciler_config}"
            "${adapter_catalog_candidate}" 1 healthy
        --output "${adapter_catalog_fleet_node_map}"
    RESULT_VARIABLE adapter_catalog_fleet_map_result
    OUTPUT_VARIABLE adapter_catalog_fleet_map_output
    ERROR_VARIABLE adapter_catalog_fleet_map_error)
if(NOT adapter_catalog_fleet_map_result EQUAL 0 OR
        NOT adapter_catalog_fleet_map_output MATCHES
            "PDR_ADAPTER_CATALOG_FLEET_NODE_MAP_PASS")
    message(FATAL_ERROR
        "Installed Fleet node map generation failed: "
        "${adapter_catalog_fleet_map_result}\n${adapter_catalog_fleet_map_output}\n"
        "${adapter_catalog_fleet_map_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${adapter_catalog_example_dir}/create_fleet_executor_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter
            "${adapter_catalog_example_dir}/fleet_node_executor_adapter.py"
        --mapping "${adapter_catalog_fleet_node_map}"
        --tools-dir "${install_dir}/bin"
        --executor-id installed-sdk-fleet
        --output "${adapter_catalog_fleet_executor_config}"
    RESULT_VARIABLE adapter_catalog_fleet_executor_result
    OUTPUT_VARIABLE adapter_catalog_fleet_executor_output
    ERROR_VARIABLE adapter_catalog_fleet_executor_error)
if(NOT adapter_catalog_fleet_executor_result EQUAL 0 OR
        NOT adapter_catalog_fleet_executor_output MATCHES
            "PDR_ADAPTER_CATALOG_FLEET_EXECUTOR_CONFIG_PASS")
    message(FATAL_ERROR
        "Installed Fleet Executor config generation failed: "
        "${adapter_catalog_fleet_executor_result}\n"
        "${adapter_catalog_fleet_executor_output}\n"
        "${adapter_catalog_fleet_executor_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${adapter_catalog_example_dir}/create_wave_gate_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter "${adapter_catalog_example_dir}/wave_gate_adapter.py"
        --gate-id installed-sdk-wave-gate
        --optional-environment PDR_WAVE_GATE_DECISION
        --output "${adapter_catalog_fleet_gate_config}"
    RESULT_VARIABLE adapter_catalog_fleet_gate_config_result
    OUTPUT_VARIABLE adapter_catalog_fleet_gate_config_output
    ERROR_VARIABLE adapter_catalog_fleet_gate_config_error)
if(NOT adapter_catalog_fleet_gate_config_result EQUAL 0 OR
        NOT adapter_catalog_fleet_gate_config_output MATCHES
            "PDR_ADAPTER_CATALOG_WAVE_GATE_CONFIG_PASS")
    message(FATAL_ERROR
        "Installed Wave Gate config generation failed: "
        "${adapter_catalog_fleet_gate_config_result}\n"
        "${adapter_catalog_fleet_gate_config_output}\n"
        "${adapter_catalog_fleet_gate_config_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${adapter_catalog_example_dir}/create_control_authorizer_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter "${adapter_catalog_example_dir}/control_authorizer_adapter.py"
        --authorizer-id installed-sdk-control-authorizer
        --optional-environment PDR_CONTROL_AUTHORIZER_DECISION
        --optional-environment PDR_CONTROL_AUTHORIZER_PRINCIPAL
        --output "${adapter_catalog_fleet_authorizer_config}"
    RESULT_VARIABLE adapter_catalog_fleet_authorizer_config_result
    OUTPUT_VARIABLE adapter_catalog_fleet_authorizer_config_output
    ERROR_VARIABLE adapter_catalog_fleet_authorizer_config_error)
if(NOT adapter_catalog_fleet_authorizer_config_result EQUAL 0 OR
        NOT adapter_catalog_fleet_authorizer_config_output MATCHES
            "PDR_ADAPTER_CATALOG_CONTROL_AUTHORIZER_CONFIG_PASS")
    message(FATAL_ERROR
        "Installed Control Authorizer config generation failed: "
        "${adapter_catalog_fleet_authorizer_config_result}\n"
        "${adapter_catalog_fleet_authorizer_config_output}\n"
        "${adapter_catalog_fleet_authorizer_config_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${leader_backend_example_dir}/create_backend_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter "${leader_backend_example_dir}/file_backend_adapter.py"
        --backend-id installed-sdk-fleet-state
        --authority-id installed-sdk-fleet-rollout-5
        --registry-id installed-sdk-adapters
        --root-environment PDR_INSTALLED_FLEET_STATE_ROOT
        --output "${adapter_catalog_fleet_state_backend_config}"
    RESULT_VARIABLE adapter_catalog_fleet_state_backend_result
    OUTPUT_VARIABLE adapter_catalog_fleet_state_backend_output
    ERROR_VARIABLE adapter_catalog_fleet_state_backend_error)
if(NOT adapter_catalog_fleet_state_backend_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Fleet state Backend config generation failed: "
        "${adapter_catalog_fleet_state_backend_result}\n"
        "${adapter_catalog_fleet_state_backend_output}\n"
        "${adapter_catalog_fleet_state_backend_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${artifact_store_example_dir}/create_artifact_store_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter "${artifact_store_example_dir}/file_artifact_store_adapter.py"
        --store-id installed-sdk-fleet-journals
        --namespace-id installed-sdk-fleet-rollout-5
        --root-environment PDR_INSTALLED_FLEET_ARTIFACT_ROOT
        --output "${adapter_catalog_fleet_artifact_config}"
    RESULT_VARIABLE adapter_catalog_fleet_artifact_result
    OUTPUT_VARIABLE adapter_catalog_fleet_artifact_output
    ERROR_VARIABLE adapter_catalog_fleet_artifact_error)
if(NOT adapter_catalog_fleet_artifact_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Fleet Artifact Store config generation failed: "
        "${adapter_catalog_fleet_artifact_result}\n"
        "${adapter_catalog_fleet_artifact_output}\n"
        "${adapter_catalog_fleet_artifact_error}")
endif()
foreach(adapter_catalog_fleet_resolver_host IN ITEMS a b)
    execute_process(
        COMMAND "${Python3_EXECUTABLE}"
            "${adapter_config_resolver_example_dir}/create_resolver_config.py"
            --python "${Python3_EXECUTABLE}"
            --adapter
                "${adapter_config_resolver_example_dir}/file_adapter_config_resolver_adapter.py"
            --resolver-id installed-sdk-fleet-config-resolver
            --scope adapter-catalog-fleet installed-sdk-fleet-rollout-5
                installed-sdk-adapters
            --entry fleet.executor revision-1 fleet-executor
                "${adapter_catalog_fleet_executor_config}"
            --entry fleet.gate revision-1 wave-gate
                "${adapter_catalog_fleet_gate_config}"
            --entry fleet.authorizer revision-1 control-authorizer
                "${adapter_catalog_fleet_authorizer_config}"
            --entry fleet.state revision-1 registry-leader-backend
                "${adapter_catalog_fleet_state_backend_config}"
            --entry fleet.artifacts revision-1 artifact-store
                "${adapter_catalog_fleet_artifact_config}"
            --mapping-output
                "${adapter_catalog_fleet_resolver_mapping_${adapter_catalog_fleet_resolver_host}}"
            --output
                "${adapter_catalog_fleet_resolver_config_${adapter_catalog_fleet_resolver_host}}"
        RESULT_VARIABLE adapter_catalog_fleet_resolver_result
        OUTPUT_VARIABLE adapter_catalog_fleet_resolver_output
        ERROR_VARIABLE adapter_catalog_fleet_resolver_error)
    if(NOT adapter_catalog_fleet_resolver_result EQUAL 0)
        message(FATAL_ERROR
            "Installed Fleet Adapter Config Resolver generation failed: "
            "${adapter_catalog_fleet_resolver_result}\n"
            "${adapter_catalog_fleet_resolver_output}\n"
            "${adapter_catalog_fleet_resolver_error}")
    endif()
endforeach()
pdr_run_installed_adapter_conformance(
    fleet-executor "${adapter_catalog_fleet_executor_config}"
    "${leader_backend_example_work}/conformance-fleet-executor.json")
pdr_run_installed_adapter_conformance(
    wave-gate "${adapter_catalog_fleet_gate_config}"
    "${leader_backend_example_work}/conformance-wave-gate.json")
pdr_run_installed_adapter_conformance(
    control-authorizer "${adapter_catalog_fleet_authorizer_config}"
    "${leader_backend_example_work}/conformance-control-authorizer.json")
pdr_run_installed_adapter_conformance(
    registry-leader-backend "${adapter_catalog_fleet_state_backend_config}"
    "${leader_backend_example_work}/conformance-state-backend.json"
    --scope-primary installed-sdk-fleet-rollout-5
    --scope-secondary installed-sdk-adapters)
pdr_run_installed_adapter_conformance(
    artifact-store "${adapter_catalog_fleet_artifact_config}"
    "${leader_backend_example_work}/conformance-artifact-store.json"
    --scope-primary installed-sdk-fleet-rollout-5)
pdr_run_installed_adapter_conformance(
    adapter-config-resolver "${adapter_catalog_fleet_resolver_config_a}"
    "${leader_backend_example_work}/conformance-adapter-config-resolver-a.json")
pdr_run_installed_adapter_conformance(
    adapter-config-resolver "${adapter_catalog_fleet_resolver_config_b}"
    "${leader_backend_example_work}/conformance-adapter-config-resolver-b.json")
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${adapter_catalog_example_dir}/create_conformance_trust_demo.py"
        --policy-id installed-sdk-adapter-certifiers
        --generation 1
        --certifier-id installed-sdk-adapter-team
        --key-id installed-sdk-certifier-key-a
        --adapter-kind adapter-config-resolver
        --adapter-kind artifact-store
        --adapter-kind control-authorizer
        --adapter-kind fleet-executor
        --adapter-kind registry-leader-backend
        --adapter-kind wave-gate
        --adapter-id installed-sdk-fleet-config-resolver
        --adapter-id installed-sdk-fleet-journals
        --adapter-id installed-sdk-control-authorizer
        --adapter-id installed-sdk-fleet
        --adapter-id installed-sdk-fleet-state
        --adapter-id installed-sdk-wave-gate
        --private-key "${adapter_catalog_fleet_trust_private_key}"
        --public-key "${adapter_catalog_fleet_trust_public_key}"
        --output "${adapter_catalog_fleet_trust_policy}"
    RESULT_VARIABLE adapter_catalog_fleet_trust_result
    OUTPUT_VARIABLE adapter_catalog_fleet_trust_output
    ERROR_VARIABLE adapter_catalog_fleet_trust_error)
if(NOT adapter_catalog_fleet_trust_result EQUAL 0 OR
        NOT adapter_catalog_fleet_trust_output MATCHES
            "PDR_ADAPTER_CONFORMANCE_TRUST_DEMO_PASS")
    message(FATAL_ERROR
        "Installed Fleet Adapter trust generation failed: "
        "${adapter_catalog_fleet_trust_result}\n"
        "${adapter_catalog_fleet_trust_output}\n"
        "${adapter_catalog_fleet_trust_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${certifier_signer_example_dir}/create_signer_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter
            "${certifier_signer_example_dir}/local_ed25519_certifier_signer_adapter.py"
        --signer-id installed-sdk-certifier-kms
        --certifier-id installed-sdk-adapter-team
        --key installed-sdk-certifier-key-a
            "${adapter_catalog_fleet_trust_public_key}"
            PDR_INSTALLED_ADAPTER_CERTIFIER_KEY
        --mapping-output "${adapter_catalog_fleet_signer_mapping}"
        --output "${adapter_catalog_fleet_signer_config}"
    RESULT_VARIABLE adapter_catalog_fleet_signer_result
    OUTPUT_VARIABLE adapter_catalog_fleet_signer_output
    ERROR_VARIABLE adapter_catalog_fleet_signer_error)
if(NOT adapter_catalog_fleet_signer_result EQUAL 0 OR
        NOT adapter_catalog_fleet_signer_output MATCHES
            "PDR_CERTIFIER_SIGNER_SAMPLE_CONFIG_PASS")
    message(FATAL_ERROR
        "Installed Fleet Certifier Signer generation failed: "
        "${adapter_catalog_fleet_signer_result}\n"
        "${adapter_catalog_fleet_signer_output}\n"
        "${adapter_catalog_fleet_signer_error}")
endif()
file(SHA256 "${adapter_catalog_fleet_signer_config}"
    adapter_catalog_fleet_signer_config_sha256)
pdr_attest_installed_adapter_conformance(
    "${leader_backend_example_work}/conformance-fleet-executor.json"
    "${adapter_catalog_fleet_attestation_executor}")
pdr_attest_installed_adapter_conformance(
    "${leader_backend_example_work}/conformance-wave-gate.json"
    "${adapter_catalog_fleet_attestation_gate}")
pdr_attest_installed_adapter_conformance(
    "${leader_backend_example_work}/conformance-control-authorizer.json"
    "${adapter_catalog_fleet_attestation_authorizer}")
pdr_attest_installed_adapter_conformance(
    "${leader_backend_example_work}/conformance-state-backend.json"
    "${adapter_catalog_fleet_attestation_state}")
pdr_attest_installed_adapter_conformance(
    "${leader_backend_example_work}/conformance-artifact-store.json"
    "${adapter_catalog_fleet_attestation_artifact}")
pdr_attest_installed_adapter_conformance(
    "${leader_backend_example_work}/conformance-adapter-config-resolver-a.json"
    "${adapter_catalog_fleet_attestation_resolver_a}")
pdr_attest_installed_adapter_conformance(
    "${leader_backend_example_work}/conformance-adapter-config-resolver-b.json"
    "${adapter_catalog_fleet_attestation_resolver_b}")
foreach(adapter_catalog_fleet_admission_host IN ITEMS a b)
    execute_process(
        COMMAND "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
            contract-package adapter-conformance-admission-create
            --bundle-id "installed-sdk-host-${adapter_catalog_fleet_admission_host}"
            --rollout-id installed-sdk-fleet-rollout-5
            --catalog-id installed-sdk-adapters
            --evidence fleet-executor
                "${leader_backend_example_work}/conformance-fleet-executor.json"
            --evidence wave-gate
                "${leader_backend_example_work}/conformance-wave-gate.json"
            --evidence control-authorizer
                "${leader_backend_example_work}/conformance-control-authorizer.json"
            --evidence registry-leader-backend
                "${leader_backend_example_work}/conformance-state-backend.json"
            --evidence artifact-store
                "${leader_backend_example_work}/conformance-artifact-store.json"
            --evidence adapter-config-resolver
                "${leader_backend_example_work}/conformance-adapter-config-resolver-${adapter_catalog_fleet_admission_host}.json"
            --attestation fleet-executor
                "${adapter_catalog_fleet_attestation_executor}"
            --attestation wave-gate
                "${adapter_catalog_fleet_attestation_gate}"
            --attestation control-authorizer
                "${adapter_catalog_fleet_attestation_authorizer}"
            --attestation registry-leader-backend
                "${adapter_catalog_fleet_attestation_state}"
            --attestation artifact-store
                "${adapter_catalog_fleet_attestation_artifact}"
            --attestation adapter-config-resolver
                "${adapter_catalog_fleet_attestation_resolver_${adapter_catalog_fleet_admission_host}}"
            --output
                "${adapter_catalog_fleet_admission_bundle_${adapter_catalog_fleet_admission_host}}"
        RESULT_VARIABLE adapter_catalog_fleet_admission_result
        OUTPUT_VARIABLE adapter_catalog_fleet_admission_output
        ERROR_VARIABLE adapter_catalog_fleet_admission_error)
    if(NOT adapter_catalog_fleet_admission_result EQUAL 0 OR
            NOT adapter_catalog_fleet_admission_output MATCHES
                "PDR_ADAPTER_CONFORMANCE_ADMISSION_CREATE_PASS")
        message(FATAL_ERROR
            "Installed Fleet admission bundle failed: "
            "${adapter_catalog_fleet_admission_result}\n"
            "${adapter_catalog_fleet_admission_output}\n"
            "${adapter_catalog_fleet_admission_error}")
    endif()
endforeach()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${adapter_catalog_example_dir}/create_fleet_plan.py"
        --rollout-id installed-sdk-fleet-rollout-5
        --catalog "${adapter_catalog_candidate}"
        --executor-config "${adapter_catalog_fleet_executor_config}"
        --gate-config "${adapter_catalog_fleet_gate_config}"
        --control-authorizer-config
            "${adapter_catalog_fleet_authorizer_config}"
        --state-backend-config
            "${adapter_catalog_fleet_state_backend_config}"
        --artifact-store-config
            "${adapter_catalog_fleet_artifact_config}"
        --adapter-config-resolver-id installed-sdk-fleet-config-resolver
        --adapter-conformance-policy-id installed-sdk-fleet-admission-v1
        --maximum-evidence-age-seconds 86400
        --adapter-conformance-trust-policy-id
            installed-sdk-adapter-certifiers
        --minimum-trust-policy-generation 1
        --config-ref fleet-executor fleet.executor revision-1
        --config-ref wave-gate fleet.gate revision-1
        --config-ref control-authorizer fleet.authorizer revision-1
        --config-ref registry-leader-backend fleet.state revision-1
        --config-ref artifact-store fleet.artifacts revision-1
        --max-parallel-nodes 2
        --wave canary canary 0 --wave wave-1 wave 0
        --node canary node-a rack-a 1
        --node wave-1 node-b rack-b 1
        --wave-gate canary 0 2 pause
        --wave-gate wave-1 0 2 pause
        --output "${adapter_catalog_fleet_plan}"
    RESULT_VARIABLE adapter_catalog_fleet_plan_result
    OUTPUT_VARIABLE adapter_catalog_fleet_plan_output
    ERROR_VARIABLE adapter_catalog_fleet_plan_error)
if(NOT adapter_catalog_fleet_plan_result EQUAL 0 OR
        NOT adapter_catalog_fleet_plan_output MATCHES
            "PDR_ADAPTER_CATALOG_FLEET_PLAN_PASS")
    message(FATAL_ERROR
        "Installed Fleet plan generation failed: "
        "${adapter_catalog_fleet_plan_result}\n${adapter_catalog_fleet_plan_output}\n"
        "${adapter_catalog_fleet_plan_error}")
endif()
file(SHA256 "${adapter_catalog_fleet_plan}"
    adapter_catalog_fleet_plan_sha256)
file(SHA256 "${adapter_catalog_fleet_resolver_config_a}"
    adapter_catalog_fleet_resolver_sha256_a)
file(SHA256 "${adapter_catalog_fleet_resolver_config_b}"
    adapter_catalog_fleet_resolver_sha256_b)
file(SHA256 "${adapter_catalog_fleet_admission_bundle_a}"
    adapter_catalog_fleet_admission_sha256_a)
file(SHA256 "${adapter_catalog_fleet_admission_bundle_b}"
    adapter_catalog_fleet_admission_sha256_b)
file(SHA256 "${adapter_catalog_fleet_trust_policy}"
    adapter_catalog_fleet_trust_policy_sha256)
if(adapter_catalog_fleet_resolver_sha256_a STREQUAL
        adapter_catalog_fleet_resolver_sha256_b)
    message(FATAL_ERROR
        "Installed Fleet Host A/B resolver configs unexpectedly have one digest")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_WAVE_GATE_STATE_ROOT=${adapter_catalog_fleet_gate_state}"
        "PDR_WAVE_GATE_DECISION=pause"
        "PDR_CONTROL_AUTHORIZER_STATE_ROOT=${adapter_catalog_fleet_authorizer_state}"
        "PDR_INSTALLED_FLEET_STATE_ROOT=${adapter_catalog_fleet_state_backend_store}"
        "PDR_INSTALLED_FLEET_ARTIFACT_ROOT=${adapter_catalog_fleet_artifact_store}"
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package adapter-catalog-fleet-run
        --plan "${adapter_catalog_fleet_plan}"
        --expected-plan-sha256 "${adapter_catalog_fleet_plan_sha256}"
        --adapter-config-resolver-config
            "${adapter_catalog_fleet_resolver_config_a}"
        --expected-adapter-config-resolver-config-sha256
            "${adapter_catalog_fleet_resolver_sha256_a}"
        --adapter-conformance-bundle
            "${adapter_catalog_fleet_admission_bundle_a}"
        --expected-adapter-conformance-bundle-sha256
            "${adapter_catalog_fleet_admission_sha256_a}"
        --adapter-conformance-trust-policy
            "${adapter_catalog_fleet_trust_policy}"
        --expected-adapter-conformance-trust-policy-sha256
            "${adapter_catalog_fleet_trust_policy_sha256}"
        --state-dir "${adapter_catalog_fleet_state}"
        --coordinator-id installed-sdk-host-a
        --report "${adapter_catalog_fleet_report}"
    RESULT_VARIABLE adapter_catalog_fleet_run_result
    OUTPUT_VARIABLE adapter_catalog_fleet_run_output
    ERROR_VARIABLE adapter_catalog_fleet_run_error)
if(NOT adapter_catalog_fleet_run_result EQUAL 2 OR
        NOT adapter_catalog_fleet_run_output MATCHES
            "PDR_ADAPTER_CATALOG_FLEET_RUN_ERROR.*status=paused")
    message(FATAL_ERROR
        "Installed Fleet rollout did not pause: ${adapter_catalog_fleet_run_result}\n"
        "${adapter_catalog_fleet_run_output}\n${adapter_catalog_fleet_run_error}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_WAVE_GATE_STATE_ROOT=${adapter_catalog_fleet_gate_state}"
        "PDR_WAVE_GATE_DECISION=pass"
        "PDR_CONTROL_AUTHORIZER_STATE_ROOT=${adapter_catalog_fleet_authorizer_state}"
        "PDR_CONTROL_AUTHORIZER_DECISION=allow"
        "PDR_CONTROL_AUTHORIZER_PRINCIPAL=installed-sdk-operator"
        "PDR_INSTALLED_FLEET_STATE_ROOT=${adapter_catalog_fleet_state_backend_store}"
        "PDR_INSTALLED_FLEET_ARTIFACT_ROOT=${adapter_catalog_fleet_artifact_store}"
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package adapter-catalog-fleet-resume
        --plan "${adapter_catalog_fleet_plan}"
        --expected-plan-sha256 "${adapter_catalog_fleet_plan_sha256}"
        --adapter-config-resolver-config
            "${adapter_catalog_fleet_resolver_config_b}"
        --expected-adapter-config-resolver-config-sha256
            "${adapter_catalog_fleet_resolver_sha256_b}"
        --adapter-conformance-bundle
            "${adapter_catalog_fleet_admission_bundle_b}"
        --expected-adapter-conformance-bundle-sha256
            "${adapter_catalog_fleet_admission_sha256_b}"
        --adapter-conformance-trust-policy
            "${adapter_catalog_fleet_trust_policy}"
        --expected-adapter-conformance-trust-policy-sha256
            "${adapter_catalog_fleet_trust_policy_sha256}"
        --state-dir "${adapter_catalog_fleet_takeover_state}"
        --coordinator-id installed-sdk-host-b
        --expected-control-generation 0
        --operation-id installed-sdk-resume
        --actor installed-sdk-operator
        --reason "installed SDK approval"
        --report "${adapter_catalog_fleet_report}"
    RESULT_VARIABLE adapter_catalog_fleet_resume_result
    OUTPUT_VARIABLE adapter_catalog_fleet_resume_output
    ERROR_VARIABLE adapter_catalog_fleet_resume_error)
if(NOT adapter_catalog_fleet_resume_result EQUAL 0 OR
        NOT adapter_catalog_fleet_resume_output MATCHES
            "PDR_ADAPTER_CATALOG_FLEET_RESUME_PASS")
    message(FATAL_ERROR
        "Installed Fleet authorized resume failed: "
        "${adapter_catalog_fleet_resume_result}\n"
        "${adapter_catalog_fleet_resume_output}\n"
        "${adapter_catalog_fleet_resume_error}")
endif()
file(READ "${adapter_catalog_fleet_report}"
    adapter_catalog_fleet_report_content)
if(NOT adapter_catalog_fleet_report_content MATCHES
        "\"status\"[ \t\r\n]*:[ \t\r\n]*\"committed\"" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"committedNodes\"[ \t\r\n]*:[ \t\r\n]*2" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"waveCount\"[ \t\r\n]*:[ \t\r\n]*2" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"schemaVersion\"[ \t\r\n]*:[ \t\r\n]*7" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"passed\"[ \t\r\n]*:[ \t\r\n]*2" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"allow\"[ \t\r\n]*:[ \t\r\n]*1" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"controlGeneration\"[ \t\r\n]*:[ \t\r\n]*1" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"lastCoordinatorId\"[ \t\r\n]*:[ \t\r\n]*\"installed-sdk-host-b\"" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"stateBackendCapabilityManifestSha256\"[ \t\r\n]*:" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"artifactStoreCapabilityManifestSha256\"[ \t\r\n]*:" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"adapterConfigResolverCapabilityManifestSha256\"[ \t\r\n]*:" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"adapterConformanceAdmissionCount\"[ \t\r\n]*:[ \t\r\n]*2" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"adapterConformanceAdmissionId\"[ \t\r\n]*:" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"adapterConformanceTrustPolicyId\"[ \t\r\n]*:[ \t\r\n]*\"installed-sdk-adapter-certifiers\"" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"adapterConformanceTrustPolicyGeneration\"[ \t\r\n]*:[ \t\r\n]*1" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"adapterConformanceTrustPolicySha256\"[ \t\r\n]*:" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"adapterConformanceSignerIds\"[ \t\r\n]*:[ \t\r\n]*\\[[ \t\r\n]*\"installed-sdk-certifier-kms\"" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"adapterConformanceSignerConfigSha256s\"[ \t\r\n]*:" OR
        NOT adapter_catalog_fleet_report_content MATCHES
        "\"adapterConformanceSignerCapabilityManifestSha256s\"[ \t\r\n]*:")
    message(FATAL_ERROR
        "Installed Fleet rollout evidence is incomplete: "
        "${adapter_catalog_fleet_report_content}")
endif()
if(EXISTS "${adapter_catalog_fleet_state}/rollouts" OR
        EXISTS "${adapter_catalog_fleet_takeover_state}/rollouts")
    message(FATAL_ERROR
        "Installed Fleet v7 wrote an authoritative local rollout journal")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${leader_backend_example_dir}/create_backend_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter "${leader_backend_example_dir}/file_backend_adapter.py"
        --backend-id installed-sdk-rotation-backend
        --authority-id installed-sdk-rotation-authority
        --registry-id installed-sdk-rotation-registry
        --root-environment PDR_INSTALLED_ROTATION_BACKEND_ROOT
        --secret-provider-config "${secret_provider_config}"
        --rotating-credential PDR_BACKEND_AUTH_TOKEN backend-auth
            deploy-2026-09 deploy-2026-08 2099-01-01T00:00:00+00:00
        --required-environment PDR_BACKEND_AUTH_TOKEN
        --minimum-credential-lease-seconds 10
        --output "${secret_rotation_backend_config}"
    RESULT_VARIABLE secret_rotation_backend_config_result
    OUTPUT_VARIABLE secret_rotation_backend_config_output
    ERROR_VARIABLE secret_rotation_backend_config_error)
if(NOT secret_rotation_backend_config_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Backend v4 config generation failed: "
        "${secret_rotation_backend_config_result}\n"
        "${secret_rotation_backend_config_output}\n"
        "${secret_rotation_backend_config_error}")
endif()
file(SHA256 "${secret_rotation_backend_config}"
    secret_rotation_backend_config_sha256)
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_INSTALLED_ROTATION_BACKEND_ROOT=${secret_rotation_backend_store}"
        PDR_INSTALLED_SDK_SECRET_OLD=pdr-installed-sdk-secret-never-persisted
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package registry-leader-backend-conformance
        --backend-config "${secret_rotation_backend_config}"
        --expected-backend-config-sha256
            "${secret_rotation_backend_config_sha256}"
        --authority-id installed-sdk-rotation-authority
        --registry-id installed-sdk-rotation-registry
        --confirm-dedicated-empty-scope
        --report "${secret_rotation_backend_report}"
    RESULT_VARIABLE secret_rotation_backend_result
    OUTPUT_VARIABLE secret_rotation_backend_output
    ERROR_VARIABLE secret_rotation_backend_error)
if(NOT secret_rotation_backend_result EQUAL 0 OR
        NOT secret_rotation_backend_output MATCHES
            "PDR_REGISTRY_LEADER_BACKEND_CONFORMANCE_PASS" OR
        NOT EXISTS "${secret_rotation_backend_report}")
    message(FATAL_ERROR
        "Installed Backend v4 rotation conformance failed: "
        "${secret_rotation_backend_result}\n${secret_rotation_backend_output}\n"
        "${secret_rotation_backend_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${leader_backend_example_dir}/create_backend_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter "${leader_backend_example_dir}/file_backend_adapter.py"
        --backend-id installed-sdk-file-adapter
        --authority-id installed-sdk-file-authority-0001
        --registry-id installed-sdk-file-registry-0001
        --output "${leader_backend_example_config}"
    RESULT_VARIABLE leader_backend_example_config_result
    OUTPUT_VARIABLE leader_backend_example_config_output
    ERROR_VARIABLE leader_backend_example_config_error)
if(NOT leader_backend_example_config_result EQUAL 0)
    message(FATAL_ERROR
        "Installed leader backend adapter config generation failed: "
        "${leader_backend_example_config_result}\n"
        "${leader_backend_example_config_output}\n"
        "${leader_backend_example_config_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${leader_backend_example_dir}/create_backend_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter "${leader_backend_example_dir}/file_backend_adapter.py"
        --backend-id installed-sdk-file-adapter-target
        --authority-id installed-sdk-file-authority-0001
        --registry-id installed-sdk-file-registry-0001
        --root-environment PDR_LEADER_BACKEND_SAMPLE_TARGET_ROOT
        --output "${leader_backend_example_target_config}"
    RESULT_VARIABLE leader_backend_target_config_result
    OUTPUT_VARIABLE leader_backend_target_config_output
    ERROR_VARIABLE leader_backend_target_config_error)
if(NOT leader_backend_target_config_result EQUAL 0)
    message(FATAL_ERROR
        "Installed leader backend target config generation failed: "
        "${leader_backend_target_config_result}\n"
        "${leader_backend_target_config_output}\n"
        "${leader_backend_target_config_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${leader_backend_example_dir}/create_backend_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter "${leader_backend_example_dir}/file_backend_adapter.py"
        --backend-id installed-sdk-migration-transaction-store
        --authority-id installed-sdk-file-migration-0001
        --registry-id installed-sdk-file-registry-0001
        --root-environment PDR_LEADER_BACKEND_SAMPLE_TRANSACTION_ROOT
        --output "${leader_backend_example_transaction_config}"
    RESULT_VARIABLE leader_backend_transaction_config_result
    OUTPUT_VARIABLE leader_backend_transaction_config_output
    ERROR_VARIABLE leader_backend_transaction_config_error)
if(NOT leader_backend_transaction_config_result EQUAL 0)
    message(FATAL_ERROR
        "Installed migration transaction config generation failed: "
        "${leader_backend_transaction_config_result}\n"
        "${leader_backend_transaction_config_output}\n"
        "${leader_backend_transaction_config_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${artifact_store_example_dir}/create_artifact_store_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter "${artifact_store_example_dir}/file_artifact_store_adapter.py"
        --store-id installed-sdk-artifact-store
        --namespace-id installed-sdk-file-migration-0001
        --root-environment PDR_ARTIFACT_STORE_SAMPLE_ROOT
        --output "${leader_backend_example_artifact_config}"
    RESULT_VARIABLE artifact_store_config_result
    OUTPUT_VARIABLE artifact_store_config_output
    ERROR_VARIABLE artifact_store_config_error)
if(NOT artifact_store_config_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Artifact Store config generation failed: "
        "${artifact_store_config_result}\n${artifact_store_config_output}\n"
        "${artifact_store_config_error}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${config_resolver_example_dir}/create_resolver_config.py"
        --python "${Python3_EXECUTABLE}"
        --adapter
            "${config_resolver_example_dir}/file_backend_config_resolver_adapter.py"
        --resolver-id installed-sdk-backend-resolver
        --entry source deploy-2026-08 "${leader_backend_example_config}"
        --entry target deploy-2026-08
            "${leader_backend_example_target_config}"
        --mapping-output "${leader_backend_example_resolver_mapping}"
        --output "${leader_backend_example_resolver_config}"
    RESULT_VARIABLE config_resolver_config_result
    OUTPUT_VARIABLE config_resolver_config_output
    ERROR_VARIABLE config_resolver_config_error)
if(NOT config_resolver_config_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Backend Config Resolver generation failed: "
        "${config_resolver_config_result}\n${config_resolver_config_output}\n"
        "${config_resolver_config_error}")
endif()
file(WRITE "${leader_backend_example_source_ref}"
    "{\n  \"kind\": \"backend-config-ref\",\n  \"resolverId\": \"installed-sdk-backend-resolver\",\n  \"configId\": \"source\",\n  \"backendId\": \"installed-sdk-file-adapter\",\n  \"revision\": \"deploy-2026-08\"\n}\n")
file(WRITE "${leader_backend_example_target_ref}"
    "{\n  \"kind\": \"backend-config-ref\",\n  \"resolverId\": \"installed-sdk-backend-resolver\",\n  \"configId\": \"target\",\n  \"backendId\": \"installed-sdk-file-adapter-target\",\n  \"revision\": \"deploy-2026-08\"\n}\n")
file(SHA256 "${leader_backend_example_config}"
    leader_backend_example_config_sha256)
file(SHA256 "${leader_backend_example_target_config}"
    leader_backend_example_target_config_sha256)
file(SHA256 "${leader_backend_example_transaction_config}"
    leader_backend_example_transaction_config_sha256)
file(SHA256 "${leader_backend_example_artifact_config}"
    leader_backend_example_artifact_config_sha256)
file(SHA256 "${leader_backend_example_resolver_config}"
    leader_backend_example_resolver_config_sha256)
file(SHA256 "${leader_backend_example_source_ref}"
    leader_backend_example_source_ref_sha256)
file(SHA256 "${leader_backend_example_target_ref}"
    leader_backend_example_target_ref_sha256)
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package registry-leader-backend-capabilities
        --backend-config "${leader_backend_example_config}"
        --expected-backend-config-sha256
            "${leader_backend_example_config_sha256}"
        --authority-id installed-sdk-file-authority-0001
        --registry-id installed-sdk-file-registry-0001
        --report "${leader_backend_example_capability_report}"
    RESULT_VARIABLE leader_backend_capability_result
    OUTPUT_VARIABLE leader_backend_capability_output
    ERROR_VARIABLE leader_backend_capability_error)
if(NOT leader_backend_capability_result EQUAL 0 OR
        NOT leader_backend_capability_output MATCHES
            "PDR_REGISTRY_LEADER_BACKEND_CAPABILITIES_PASS" OR
        NOT EXISTS "${leader_backend_example_capability_report}")
    message(FATAL_ERROR
        "Installed leader backend capability negotiation failed: "
        "${leader_backend_capability_result}\n"
        "${leader_backend_capability_output}\n"
        "${leader_backend_capability_error}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_LEADER_BACKEND_SAMPLE_ROOT=${leader_backend_example_store}"
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package registry-leader-backend-conformance
        --backend-config "${leader_backend_example_config}"
        --expected-backend-config-sha256
            "${leader_backend_example_config_sha256}"
        --authority-id installed-sdk-file-authority-0001
        --registry-id installed-sdk-file-registry-0001
        --confirm-dedicated-empty-scope
        --report "${leader_backend_example_report}"
    RESULT_VARIABLE leader_backend_example_result
    OUTPUT_VARIABLE leader_backend_example_output
    ERROR_VARIABLE leader_backend_example_error)
if(NOT leader_backend_example_result EQUAL 0 OR
        NOT leader_backend_example_output MATCHES
            "PDR_REGISTRY_LEADER_BACKEND_CONFORMANCE_PASS" OR
        NOT EXISTS "${leader_backend_example_report}")
    message(FATAL_ERROR
        "Installed leader backend adapter conformance failed: "
        "${leader_backend_example_result}\n${leader_backend_example_output}\n"
        "${leader_backend_example_error}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_LEADER_BACKEND_SAMPLE_ROOT=${leader_backend_example_store}"
        "PDR_LEADER_BACKEND_SAMPLE_TARGET_ROOT=${leader_backend_example_target_store}"
        "PDR_LEADER_BACKEND_SAMPLE_TRANSACTION_ROOT=${leader_backend_example_transaction_store}"
        "PDR_ARTIFACT_STORE_SAMPLE_ROOT=${leader_backend_example_artifact_store}"
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package registry-leader-backend-migration-sync
        --migration-id installed-sdk-file-migration-0001
        --authority-id installed-sdk-file-authority-0001
        --registry-id installed-sdk-file-registry-0001
        --source-backend-ref "${leader_backend_example_source_ref}"
        --expected-source-backend-ref-sha256
            "${leader_backend_example_source_ref_sha256}"
        --target-backend-ref "${leader_backend_example_target_ref}"
        --expected-target-backend-ref-sha256
            "${leader_backend_example_target_ref_sha256}"
        --backend-config-resolver-config
            "${leader_backend_example_resolver_config}"
        --expected-backend-config-resolver-config-sha256
            "${leader_backend_example_resolver_config_sha256}"
        --confirm-target-migration-scope
        --transaction-backend-config
            "${leader_backend_example_transaction_config}"
        --expected-transaction-backend-config-sha256
            "${leader_backend_example_transaction_config_sha256}"
        --artifact-store-config "${leader_backend_example_artifact_config}"
        --expected-artifact-store-config-sha256
            "${leader_backend_example_artifact_config_sha256}"
        --actor installed-sdk-operator
        --output "${leader_backend_example_migration_sync}"
    RESULT_VARIABLE leader_backend_migration_sync_result
    OUTPUT_VARIABLE leader_backend_migration_sync_output
    ERROR_VARIABLE leader_backend_migration_sync_error)
if(NOT leader_backend_migration_sync_result EQUAL 0 OR
        NOT leader_backend_migration_sync_output MATCHES
            "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_SYNC_PASS" OR
        NOT EXISTS "${leader_backend_example_migration_sync}")
    message(FATAL_ERROR
        "Installed leader backend migration sync failed: "
        "${leader_backend_migration_sync_result}\n"
        "${leader_backend_migration_sync_output}\n"
        "${leader_backend_migration_sync_error}")
endif()
string(REGEX MATCH "state-sha256=([0-9a-f]+)"
    leader_backend_migration_state_match
    "${leader_backend_migration_sync_output}")
set(leader_backend_example_migration_transaction_sha256 "${CMAKE_MATCH_1}")
string(LENGTH "${leader_backend_example_migration_transaction_sha256}"
    leader_backend_example_migration_transaction_sha256_length)
if(NOT leader_backend_example_migration_transaction_sha256_length EQUAL 64)
    message(FATAL_ERROR
        "Installed migration sync did not report transaction state SHA: "
        "${leader_backend_migration_sync_output}")
endif()
file(REMOVE "${leader_backend_example_migration_sync}")
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_LEADER_BACKEND_SAMPLE_ROOT=${leader_backend_example_store}"
        "PDR_LEADER_BACKEND_SAMPLE_TARGET_ROOT=${leader_backend_example_target_store}"
        "PDR_LEADER_BACKEND_SAMPLE_TRANSACTION_ROOT=${leader_backend_example_transaction_store}"
        "PDR_ARTIFACT_STORE_SAMPLE_ROOT=${leader_backend_example_artifact_store}"
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package registry-leader-backend-migration-resume
        --transaction-backend-config
            "${leader_backend_example_transaction_config}"
        --expected-transaction-backend-config-sha256
            "${leader_backend_example_transaction_config_sha256}"
        --artifact-store-config "${leader_backend_example_artifact_config}"
        --expected-artifact-store-config-sha256
            "${leader_backend_example_artifact_config_sha256}"
        --backend-config-resolver-config
            "${leader_backend_example_resolver_config}"
        --expected-backend-config-resolver-config-sha256
            "${leader_backend_example_resolver_config_sha256}"
        --migration-id installed-sdk-file-migration-0001
        --registry-id installed-sdk-file-registry-0001
        --expected-transaction-sha256
            "${leader_backend_example_migration_transaction_sha256}"
        --actor installed-sdk-handoff-operator
        --confirm-target-migration-scope
        --output "${leader_backend_example_migration_resume}"
    RESULT_VARIABLE leader_backend_migration_resume_result
    OUTPUT_VARIABLE leader_backend_migration_resume_output
    ERROR_VARIABLE leader_backend_migration_resume_error)
if(NOT leader_backend_migration_resume_result EQUAL 0 OR
        NOT leader_backend_migration_resume_output MATCHES
            "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_RESUME_PASS" OR
        NOT EXISTS "${leader_backend_example_migration_resume}")
    message(FATAL_ERROR
        "Installed leader backend migration resume failed: "
        "${leader_backend_migration_resume_result}\n"
        "${leader_backend_migration_resume_output}\n"
        "${leader_backend_migration_resume_error}")
endif()

# The installed distributed adapter must remain executable independently of the
# source copy. A deterministic etcdctl transaction model exercises the installed
# config generator, cluster preflight and public conformance command.
set(leader_etcd_example_dir
    "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl")
set(leader_etcd_example_work
    "${PDR_BINARY_DIR}/sdk-leader-etcd-adapter-example")
set(leader_etcd_example_store "${leader_etcd_example_work}/store")
set(leader_etcd_adapter_config "${leader_etcd_example_work}/adapter.json")
set(leader_etcd_backend_config "${leader_etcd_example_work}/backend.json")
set(leader_etcd_preflight_report "${leader_etcd_example_work}/preflight.json")
set(leader_etcd_acceptance_directory "${leader_etcd_example_work}/acceptance")
set(leader_etcd_migration_sync
    "${leader_etcd_example_work}/migration-transaction-sync.json")
set(leader_etcd_migration_resume
    "${leader_etcd_example_work}/migration-transaction-resume.json")
file(REMOVE_RECURSE "${leader_etcd_example_work}")
file(MAKE_DIRECTORY "${leader_etcd_example_store}")
file(WRITE "${leader_etcd_example_work}/ca.pem" "sdk-test-ca\n")
file(WRITE "${leader_etcd_example_work}/client.pem" "sdk-test-cert\n")
file(WRITE "${leader_etcd_example_work}/client-key.pem" "sdk-test-key\n")
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${leader_etcd_example_dir}/create_backend_configs.py"
        --python "${Python3_EXECUTABLE}"
        --adapter "${leader_etcd_example_dir}/etcd_backend_adapter.py"
        --adapter-id installed-sdk-etcd-adapter
        --backend-id installed-sdk-etcd-backend
        --authority-id installed-sdk-etcd-authority-0001
        --authority-id installed-sdk-etcd-transaction-migration-0001
        --registry-id installed-sdk-etcd-registry-0001
        --registry-id installed-sdk-file-registry-0001
        --etcdctl "${Python3_EXECUTABLE}"
        --etcdctl-argument
            "${PDR_SOURCE_DIR}/tools/tests/fixtures/fake_etcdctl.py"
        --etcdctl-artifact
            "${PDR_SOURCE_DIR}/tools/tests/fixtures/fake_etcdctl.py"
        --etcdctl-environment PDR_TEST_ETCDCTL_ROOT
        --etcdctl-environment PDR_TEST_ETCDCTL_MODE
        --endpoint https://etcd-1.example:2379
        --endpoint https://etcd-2.example:2379
        --endpoint https://etcd-3.example:2379
        --key-prefix /pdr/installed-sdk/leader/v1
        --cacert "${leader_etcd_example_work}/ca.pem"
        --cert "${leader_etcd_example_work}/client.pem"
        --key "${leader_etcd_example_work}/client-key.pem"
        --adapter-config-output "${leader_etcd_adapter_config}"
        --backend-config-output "${leader_etcd_backend_config}"
    RESULT_VARIABLE leader_etcd_config_result
    OUTPUT_VARIABLE leader_etcd_config_output
    ERROR_VARIABLE leader_etcd_config_error)
if(NOT leader_etcd_config_result EQUAL 0)
    message(FATAL_ERROR
        "Installed leader etcd config generation failed: "
        "${leader_etcd_config_result}\n${leader_etcd_config_output}\n"
        "${leader_etcd_config_error}")
endif()
file(SHA256 "${leader_etcd_adapter_config}" leader_etcd_adapter_config_sha256)
file(SHA256 "${leader_etcd_backend_config}" leader_etcd_backend_config_sha256)
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_TEST_ETCDCTL_ROOT=${leader_etcd_example_store}"
        "PDR_TEST_ETCDCTL_MODE=normal"
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package registry-leader-etcd-preflight
        --config "${leader_etcd_adapter_config}"
        --expected-config-sha256 "${leader_etcd_adapter_config_sha256}"
        --report "${leader_etcd_preflight_report}"
    RESULT_VARIABLE leader_etcd_preflight_result
    OUTPUT_VARIABLE leader_etcd_preflight_output
    ERROR_VARIABLE leader_etcd_preflight_error)
if(NOT leader_etcd_preflight_result EQUAL 0 OR
        NOT leader_etcd_preflight_output MATCHES
            "PDR_LEADER_ETCD_PREFLIGHT_PASS" OR
        NOT EXISTS "${leader_etcd_preflight_report}")
    message(FATAL_ERROR
        "Installed leader etcd cluster preflight failed: "
        "${leader_etcd_preflight_result}\n${leader_etcd_preflight_output}\n"
        "${leader_etcd_preflight_error}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_TEST_ETCDCTL_ROOT=${leader_etcd_example_store}"
        "PDR_TEST_ETCDCTL_MODE=normal"
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package registry-leader-etcd-acceptance
        --adapter-config "${leader_etcd_adapter_config}"
        --expected-adapter-config-sha256
            "${leader_etcd_adapter_config_sha256}"
        --backend-config "${leader_etcd_backend_config}"
        --expected-backend-config-sha256 "${leader_etcd_backend_config_sha256}"
        --authority-id installed-sdk-etcd-authority-0001
        --registry-id installed-sdk-etcd-registry-0001
        --confirm-dedicated-empty-scope
        --output-directory "${leader_etcd_acceptance_directory}"
    RESULT_VARIABLE leader_etcd_acceptance_result
    OUTPUT_VARIABLE leader_etcd_acceptance_output
    ERROR_VARIABLE leader_etcd_acceptance_error)
if(NOT leader_etcd_acceptance_result EQUAL 0 OR
        NOT leader_etcd_acceptance_output MATCHES
            "PDR_REGISTRY_LEADER_ETCD_ACCEPTANCE_PASS" OR
        NOT EXISTS "${leader_etcd_acceptance_directory}/acceptance.json")
    message(FATAL_ERROR
        "Installed leader etcd adapter acceptance failed: "
        "${leader_etcd_acceptance_result}\n${leader_etcd_acceptance_output}\n"
        "${leader_etcd_acceptance_error}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_LEADER_BACKEND_SAMPLE_ROOT=${leader_backend_example_store}"
        "PDR_LEADER_BACKEND_SAMPLE_TARGET_ROOT=${leader_backend_example_target_store}"
        "PDR_TEST_ETCDCTL_ROOT=${leader_etcd_example_store}"
        "PDR_TEST_ETCDCTL_MODE=normal"
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package registry-leader-backend-migration-sync
        --migration-id installed-sdk-etcd-transaction-migration-0001
        --authority-id installed-sdk-file-authority-0001
        --registry-id installed-sdk-file-registry-0001
        --source-backend-config "${leader_backend_example_config}"
        --expected-source-backend-config-sha256
            "${leader_backend_example_config_sha256}"
        --target-backend-config "${leader_backend_example_target_config}"
        --expected-target-backend-config-sha256
            "${leader_backend_example_target_config_sha256}"
        --confirm-target-migration-scope
        --transaction-backend-config "${leader_etcd_backend_config}"
        --expected-transaction-backend-config-sha256
            "${leader_etcd_backend_config_sha256}"
        --actor installed-sdk-etcd-operator
        --output "${leader_etcd_migration_sync}"
    RESULT_VARIABLE leader_etcd_migration_sync_result
    OUTPUT_VARIABLE leader_etcd_migration_sync_output
    ERROR_VARIABLE leader_etcd_migration_sync_error)
if(NOT leader_etcd_migration_sync_result EQUAL 0 OR
        NOT leader_etcd_migration_sync_output MATCHES
            "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_SYNC_PASS" OR
        NOT EXISTS "${leader_etcd_migration_sync}")
    message(FATAL_ERROR
        "Installed etcd transaction-store migration sync failed: "
        "${leader_etcd_migration_sync_result}\n"
        "${leader_etcd_migration_sync_output}\n"
        "${leader_etcd_migration_sync_error}")
endif()
string(REGEX MATCH "state-sha256=([0-9a-f]+)"
    leader_etcd_migration_state_match
    "${leader_etcd_migration_sync_output}")
set(leader_etcd_migration_state_sha256 "${CMAKE_MATCH_1}")
string(LENGTH "${leader_etcd_migration_state_sha256}"
    leader_etcd_migration_state_sha256_length)
if(NOT leader_etcd_migration_state_sha256_length EQUAL 64)
    message(FATAL_ERROR
        "Installed etcd migration sync lacks state SHA: "
        "${leader_etcd_migration_sync_output}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_LEADER_BACKEND_SAMPLE_ROOT=${leader_backend_example_store}"
        "PDR_LEADER_BACKEND_SAMPLE_TARGET_ROOT=${leader_backend_example_target_store}"
        "PDR_TEST_ETCDCTL_ROOT=${leader_etcd_example_store}"
        "PDR_TEST_ETCDCTL_MODE=normal"
        "${Python3_EXECUTABLE}" "${install_dir}/bin/pdr.py"
        contract-package registry-leader-backend-migration-resume
        --transaction-backend-config "${leader_etcd_backend_config}"
        --expected-transaction-backend-config-sha256
            "${leader_etcd_backend_config_sha256}"
        --migration-id installed-sdk-etcd-transaction-migration-0001
        --registry-id installed-sdk-file-registry-0001
        --expected-transaction-sha256
            "${leader_etcd_migration_state_sha256}"
        --actor installed-sdk-etcd-handoff
        --confirm-target-migration-scope
        --output "${leader_etcd_migration_resume}"
    RESULT_VARIABLE leader_etcd_migration_resume_result
    OUTPUT_VARIABLE leader_etcd_migration_resume_output
    ERROR_VARIABLE leader_etcd_migration_resume_error)
if(NOT leader_etcd_migration_resume_result EQUAL 0 OR
        NOT leader_etcd_migration_resume_output MATCHES
            "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_RESUME_PASS" OR
        NOT EXISTS "${leader_etcd_migration_resume}")
    message(FATAL_ERROR
        "Installed etcd transaction-store migration resume failed: "
        "${leader_etcd_migration_resume_result}\n"
        "${leader_etcd_migration_resume_output}\n"
        "${leader_etcd_migration_resume_error}")
endif()

# A product component must be able to consume the installed CMake conformance
# function and installed Python tool without starting the framework Runtime.
set(component_contract_configure_command "${CMAKE_COMMAND}"
    -S "${PDR_SOURCE_DIR}/tests/component-contract-consumer"
    -B "${component_contract_build_dir}"
    -G "${PDR_GENERATOR}"
    "-DCMAKE_PREFIX_PATH=${consumer_prefix_path}"
    "-DPoco_DIR=${PDR_DEPENDENCY_PREFIX}/cmake")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND component_contract_configure_command
        -A "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${component_contract_configure_command}
    RESULT_VARIABLE component_contract_configure_result)
if(NOT component_contract_configure_result EQUAL 0)
    message(FATAL_ERROR
        "Installed component contract consumer configure failed: "
        "${component_contract_configure_result}")
endif()
execute_process(
    COMMAND "${CMAKE_CTEST_COMMAND}"
        --test-dir "${component_contract_build_dir}"
        -C "${PDR_CONFIG}" --output-on-failure
    RESULT_VARIABLE component_contract_test_result)
if(NOT component_contract_test_result EQUAL 0)
    message(FATAL_ERROR
        "Installed component contract consumer test failed: "
        "${component_contract_test_result}")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${install_dir}/bin/component_contract_test.py"
        --verify-report
        "${component_contract_build_dir}/reports/order-workflow-contract.json"
    RESULT_VARIABLE component_contract_evidence_result)
if(NOT component_contract_evidence_result EQUAL 0)
    message(FATAL_ERROR
        "Installed component contract evidence verification failed: "
        "${component_contract_evidence_result}")
endif()

set(configure_command "${CMAKE_COMMAND}"
    -S "${PDR_SOURCE_DIR}/tests/sdk-consumer"
    -B "${consumer_build_dir}"
    -G "${PDR_GENERATOR}"
    "-DCMAKE_PREFIX_PATH=${consumer_prefix_path}"
    "-DPoco_DIR=${PDR_DEPENDENCY_PREFIX}/cmake")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND configure_command -A "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${configure_command} RESULT_VARIABLE configure_result)
if(NOT configure_result EQUAL 0)
    message(FATAL_ERROR "External SDK consumer configure failed: ${configure_result}")
endif()

execute_process(
    COMMAND "${CMAKE_COMMAND}" --build "${consumer_build_dir}"
        --config "${PDR_CONFIG}"
    RESULT_VARIABLE build_result)
if(NOT build_result EQUAL 0)
    message(FATAL_ERROR "External SDK consumer build failed: ${build_result}")
endif()

set(consumer_executable "${consumer_build_dir}/pdr-sdk-consumer")
if(WIN32)
    set(consumer_executable "${consumer_build_dir}/${PDR_CONFIG}/pdr-sdk-consumer.exe")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
        "${consumer_executable}"
    RESULT_VARIABLE run_result)
if(NOT run_result EQUAL 0)
    message(FATAL_ERROR "External SDK consumer run failed: ${run_result}")
endif()

# The versioned Fast DDS boundary must be consumable by a project that enables
# only the C language. This prevents C++ compile features or private Fast DDS
# types from leaking through the installed target.
set(fastdds_abi_c_configure_command "${CMAKE_COMMAND}"
    -S "${PDR_SOURCE_DIR}/tests/fastdds-abi-c-consumer"
    -B "${fastdds_abi_c_build_dir}"
    -G "${PDR_GENERATOR}"
    "-DCMAKE_PREFIX_PATH=${consumer_prefix_path}"
    "-DPoco_DIR=${PDR_DEPENDENCY_PREFIX}/cmake")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND fastdds_abi_c_configure_command
        -A "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${fastdds_abi_c_configure_command}
    RESULT_VARIABLE fastdds_abi_c_configure_result)
if(NOT fastdds_abi_c_configure_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Fast DDS C ABI consumer configure failed: "
        "${fastdds_abi_c_configure_result}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" --build "${fastdds_abi_c_build_dir}"
        --config "${PDR_CONFIG}"
    RESULT_VARIABLE fastdds_abi_c_build_result)
if(NOT fastdds_abi_c_build_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Fast DDS C ABI consumer build failed: ${fastdds_abi_c_build_result}")
endif()
set(fastdds_abi_c_executable
    "${fastdds_abi_c_build_dir}/pdr-fastdds-abi-c-consumer")
if(WIN32)
    set(fastdds_abi_c_executable
        "${fastdds_abi_c_build_dir}/${PDR_CONFIG}/pdr-fastdds-abi-c-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${fastdds_abi_c_executable}"
    RESULT_VARIABLE fastdds_abi_c_run_result
    OUTPUT_VARIABLE fastdds_abi_c_run_output
    ERROR_VARIABLE fastdds_abi_c_run_error)
if(NOT fastdds_abi_c_run_result EQUAL 0 OR
        NOT fastdds_abi_c_run_output MATCHES
            "FAST_DDS_ABI_C_CONSUMER_PASS language=C layout=verified lifecycle=verified")
    message(FATAL_ERROR
        "Installed Fast DDS C ABI consumer run failed: ${fastdds_abi_c_run_result}\n"
        "${fastdds_abi_c_run_output}\n${fastdds_abi_c_run_error}")
endif()

# Workflow providers must compile against the small installed API component,
# while custom hosts can opt into the concrete core/storage implementation.
set(workflow_configure_command "${CMAKE_COMMAND}"
    -S "${PDR_SOURCE_DIR}/tests/workflow-consumer"
    -B "${workflow_build_dir}"
    -G "${PDR_GENERATOR}"
    "-DCMAKE_PREFIX_PATH=${consumer_prefix_path}"
    "-DPoco_DIR=${PDR_DEPENDENCY_PREFIX}/cmake")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND workflow_configure_command -A "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${workflow_configure_command}
    RESULT_VARIABLE workflow_configure_result)
if(NOT workflow_configure_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Workflow consumer configure failed: ${workflow_configure_result}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" --build "${workflow_build_dir}"
        --config "${PDR_CONFIG}"
    RESULT_VARIABLE workflow_build_result)
if(NOT workflow_build_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Workflow consumer build failed: ${workflow_build_result}")
endif()
set(workflow_executable "${workflow_build_dir}/pdr-workflow-consumer")
if(WIN32)
    set(workflow_executable
        "${workflow_build_dir}/${PDR_CONFIG}/pdr-workflow-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${workflow_executable}"
    RESULT_VARIABLE workflow_run_result)
if(NOT workflow_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Workflow consumer run failed: ${workflow_run_result}")
endif()
set(workflow_api_executable "${workflow_build_dir}/pdr-workflow-api-consumer")
if(WIN32)
    set(workflow_api_executable
        "${workflow_build_dir}/${PDR_CONFIG}/pdr-workflow-api-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${workflow_api_executable}"
    RESULT_VARIABLE workflow_api_run_result)
if(NOT workflow_api_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed WorkflowAPI-only consumer run failed: ${workflow_api_run_result}")
endif()
set(store_forward_api_executable
    "${workflow_build_dir}/pdr-store-forward-api-consumer")
if(WIN32)
    set(store_forward_api_executable
        "${workflow_build_dir}/${PDR_CONFIG}/pdr-store-forward-api-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${store_forward_api_executable}"
    RESULT_VARIABLE store_forward_api_run_result)
if(NOT store_forward_api_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed StoreForwardAPI-only consumer run failed: ${store_forward_api_run_result}")
endif()

set(transport_provider_executable
    "${workflow_build_dir}/pdr-transport-provider-api-consumer")
if(WIN32)
    set(transport_provider_executable
        "${workflow_build_dir}/${PDR_CONFIG}/pdr-transport-provider-api-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${transport_provider_executable}"
    RESULT_VARIABLE transport_provider_run_result)
if(NOT transport_provider_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed TransportProvider consumer run failed: ${transport_provider_run_result}")
endif()

set(config_transaction_executable
    "${workflow_build_dir}/pdr-config-transaction-api-consumer")
if(WIN32)
    set(config_transaction_executable
        "${workflow_build_dir}/${PDR_CONFIG}/pdr-config-transaction-api-consumer.exe")
endif()

set(scheduling_configuration_executable
    "${workflow_build_dir}/pdr-scheduling-configuration-consumer")
if(WIN32)
    set(scheduling_configuration_executable
        "${workflow_build_dir}/${PDR_CONFIG}/pdr-scheduling-configuration-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${scheduling_configuration_executable}"
    RESULT_VARIABLE scheduling_configuration_run_result)
if(NOT scheduling_configuration_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed SchedulingConfiguration consumer run failed: ${scheduling_configuration_run_result}")
endif()

set(service_dependency_executable
    "${workflow_build_dir}/pdr-service-dependency-consumer")
if(WIN32)
    set(service_dependency_executable
        "${workflow_build_dir}/${PDR_CONFIG}/pdr-service-dependency-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${service_dependency_executable}"
    RESULT_VARIABLE service_dependency_run_result)
if(NOT service_dependency_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed ServiceDependency consumer run failed: ${service_dependency_run_result}")
endif()

set(lifecycle_executable
    "${workflow_build_dir}/pdr-lifecycle-consumer")
if(WIN32)
    set(lifecycle_executable
        "${workflow_build_dir}/${PDR_CONFIG}/pdr-lifecycle-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${lifecycle_executable}"
    RESULT_VARIABLE lifecycle_run_result)
if(NOT lifecycle_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed LifecycleCore consumer run failed: ${lifecycle_run_result}")
endif()

set(lifecycle_persistence_executable
    "${workflow_build_dir}/pdr-lifecycle-persistence-consumer")
if(WIN32)
    set(lifecycle_persistence_executable
        "${workflow_build_dir}/${PDR_CONFIG}/pdr-lifecycle-persistence-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${lifecycle_persistence_executable}"
    RESULT_VARIABLE lifecycle_persistence_run_result)
if(NOT lifecycle_persistence_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed LifecyclePersistence consumer run failed: ${lifecycle_persistence_run_result}")
endif()

set(membership_executable
    "${consumer_build_dir}/pdr-membership-sdk-consumer")
if(WIN32)
    set(membership_executable
        "${consumer_build_dir}/${PDR_CONFIG}/pdr-membership-sdk-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${membership_executable}"
    RESULT_VARIABLE membership_run_result)
if(NOT membership_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Membership components consumer run failed: ${membership_run_result}")
endif()

set(service_directory_executable
    "${consumer_build_dir}/pdr-service-directory-sdk-consumer")
if(WIN32)
    set(service_directory_executable
        "${consumer_build_dir}/${PDR_CONFIG}/pdr-service-directory-sdk-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${service_directory_executable}"
    RESULT_VARIABLE service_directory_run_result)
if(NOT service_directory_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed ServiceDirectory components consumer run failed: ${service_directory_run_result}")
endif()

set(service_client_executable
    "${consumer_build_dir}/pdr-service-client-sdk-consumer")
if(WIN32)
    set(service_client_executable
        "${consumer_build_dir}/${PDR_CONFIG}/pdr-service-client-sdk-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${service_client_executable}"
    RESULT_VARIABLE service_client_run_result)
if(NOT service_client_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed ServiceClient component consumer run failed: ${service_client_run_result}")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${config_transaction_executable}"
    RESULT_VARIABLE config_transaction_run_result)
if(NOT config_transaction_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed ConfigTransaction consumer run failed: ${config_transaction_run_result}")
endif()

set(schema_registry_executable
    "${workflow_build_dir}/pdr-schema-registry-api-consumer")
if(WIN32)
    set(schema_registry_executable
        "${workflow_build_dir}/${PDR_CONFIG}/pdr-schema-registry-api-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${schema_registry_executable}"
    RESULT_VARIABLE schema_registry_run_result)
if(NOT schema_registry_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed SchemaRegistry consumer run failed: ${schema_registry_run_result}")
endif()

set(capabilities_executable
    "${workflow_build_dir}/pdr-capabilities-api-consumer")
if(WIN32)
    set(capabilities_executable
        "${workflow_build_dir}/${PDR_CONFIG}/pdr-capabilities-api-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${capabilities_executable}"
    RESULT_VARIABLE capabilities_run_result)
if(NOT capabilities_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed Capabilities consumer run failed: ${capabilities_run_result}")
endif()

# Optional distributed transports must be consumable from the installed package,
# not only from targets in the framework source tree.
set(transport_configure_command "${CMAKE_COMMAND}"
    -S "${PDR_SOURCE_DIR}/tests/transport-consumer"
    -B "${transport_build_dir}"
    -G "${PDR_GENERATOR}"
    "-DCMAKE_PREFIX_PATH=${consumer_prefix_path}"
    "-DPoco_DIR=${PDR_DEPENDENCY_PREFIX}/cmake"
    "-DPDR_TEST_MQTT_TRANSPORT=${PDR_TEST_MQTT_TRANSPORT}"
    "-DPDR_TEST_FASTDDS_TRANSPORT=${PDR_TEST_FASTDDS_TRANSPORT}")
if(PDR_GENERATOR_PLATFORM)
    list(APPEND transport_configure_command -A "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${transport_configure_command}
    RESULT_VARIABLE transport_configure_result)
if(NOT transport_configure_result EQUAL 0)
    message(FATAL_ERROR
        "Installed transport consumer configure failed: ${transport_configure_result}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" --build "${transport_build_dir}"
        --config "${PDR_CONFIG}"
    RESULT_VARIABLE transport_build_result)
if(NOT transport_build_result EQUAL 0)
    message(FATAL_ERROR
        "Installed transport consumer build failed: ${transport_build_result}")
endif()
set(transport_executable "${transport_build_dir}/pdr-transport-consumer")
if(WIN32)
    set(transport_executable
        "${transport_build_dir}/${PDR_CONFIG}/pdr-transport-consumer.exe")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env
    "PATH=${install_dir}/bin\;${PDR_DEPENDENCY_PREFIX}/bin\;$ENV{PATH}"
    "${transport_executable}"
    RESULT_VARIABLE transport_run_result)
if(NOT transport_run_result EQUAL 0)
    message(FATAL_ERROR
        "Installed transport consumer run failed: ${transport_run_result}")
endif()

# A foundation-only consumer must not need the optional Paho dependency.
set(foundation_configure_command "${CMAKE_COMMAND}"
    -S "${PDR_SOURCE_DIR}/tests/sdk-consumer"
    -B "${foundation_build_dir}"
    -G "${PDR_GENERATOR}"
    "-DCMAKE_PREFIX_PATH=${consumer_prefix_path}"
    "-DPoco_DIR=${PDR_DEPENDENCY_PREFIX}/cmake"
    -DPDR_SDK_CONSUMER_PROTOCOLS=OFF
    -DCMAKE_DISABLE_FIND_PACKAGE_eclipse-paho-mqtt-c=TRUE)
if(PDR_GENERATOR_PLATFORM)
    list(APPEND foundation_configure_command -A "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${foundation_configure_command}
    RESULT_VARIABLE foundation_configure_result)
if(NOT foundation_configure_result EQUAL 0)
    message(FATAL_ERROR
        "Foundation-only SDK consumer configure failed: ${foundation_configure_result}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" --build "${foundation_build_dir}"
        --config "${PDR_CONFIG}"
    RESULT_VARIABLE foundation_build_result)
if(NOT foundation_build_result EQUAL 0)
    message(FATAL_ERROR
        "Foundation-only SDK consumer build failed: ${foundation_build_result}")
endif()
set(foundation_executable "${foundation_build_dir}/pdr-sdk-consumer")
if(WIN32)
    set(foundation_executable
        "${foundation_build_dir}/${PDR_CONFIG}/pdr-sdk-consumer.exe")
endif()
execute_process(COMMAND "${foundation_executable}"
    RESULT_VARIABLE foundation_run_result)
if(NOT foundation_run_result EQUAL 0)
    message(FATAL_ERROR
        "Foundation-only SDK consumer run failed: ${foundation_run_result}")
endif()

# Unknown requested components must fail during find_package with a clear boundary.
set(unknown_configure_command "${CMAKE_COMMAND}"
    -S "${PDR_SOURCE_DIR}/tests/sdk-consumer"
    -B "${unknown_build_dir}"
    -G "${PDR_GENERATOR}"
    "-DCMAKE_PREFIX_PATH=${consumer_prefix_path}"
    "-DPoco_DIR=${PDR_DEPENDENCY_PREFIX}/cmake"
    -DPDR_SDK_CONSUMER_UNKNOWN_COMPONENT=ON)
if(PDR_GENERATOR_PLATFORM)
    list(APPEND unknown_configure_command -A "${PDR_GENERATOR_PLATFORM}")
endif()
execute_process(COMMAND ${unknown_configure_command}
    RESULT_VARIABLE unknown_configure_result
    OUTPUT_QUIET ERROR_QUIET)
if(unknown_configure_result EQUAL 0)
    message(FATAL_ERROR "Unknown PocoDDSRuntime component was unexpectedly accepted")
endif()
