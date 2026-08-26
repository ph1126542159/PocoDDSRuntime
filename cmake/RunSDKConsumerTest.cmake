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
        "${install_dir}/bin/team_contract_registry_leader_backend_conformance.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-file/file_backend_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-file/create_backend_config.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-file/README.md"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl/etcd_backend_adapter.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl/create_backend_configs.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl/etcd_cluster_preflight.py"
        "${install_dir}/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl/README.md"
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
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-request.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-response.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-backend-conformance.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-etcd-adapter-config.schema.json"
        "${install_dir}/share/PocoDDSRuntime/contracts/schemas/team-contract-registry-leader-etcd-preflight.schema.json"
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
set(leader_backend_example_work
    "${PDR_BINARY_DIR}/sdk-leader-backend-adapter-example")
set(leader_backend_example_store "${leader_backend_example_work}/store")
set(leader_backend_example_config "${leader_backend_example_work}/backend.json")
set(leader_backend_example_report "${leader_backend_example_work}/conformance.json")
file(REMOVE_RECURSE "${leader_backend_example_work}")
file(MAKE_DIRECTORY "${leader_backend_example_store}")
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
file(SHA256 "${leader_backend_example_config}"
    leader_backend_example_config_sha256)
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
set(leader_etcd_conformance_report "${leader_etcd_example_work}/conformance.json")
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
        --registry-id installed-sdk-etcd-registry-0001
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
        contract-package registry-leader-backend-conformance
        --backend-config "${leader_etcd_backend_config}"
        --expected-backend-config-sha256 "${leader_etcd_backend_config_sha256}"
        --authority-id installed-sdk-etcd-authority-0001
        --registry-id installed-sdk-etcd-registry-0001
        --confirm-dedicated-empty-scope
        --report "${leader_etcd_conformance_report}"
    RESULT_VARIABLE leader_etcd_conformance_result
    OUTPUT_VARIABLE leader_etcd_conformance_output
    ERROR_VARIABLE leader_etcd_conformance_error)
if(NOT leader_etcd_conformance_result EQUAL 0 OR
        NOT leader_etcd_conformance_output MATCHES
            "PDR_REGISTRY_LEADER_BACKEND_CONFORMANCE_PASS" OR
        NOT EXISTS "${leader_etcd_conformance_report}")
    message(FATAL_ERROR
        "Installed leader etcd adapter conformance failed: "
        "${leader_etcd_conformance_result}\n${leader_etcd_conformance_output}\n"
        "${leader_etcd_conformance_error}")
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
