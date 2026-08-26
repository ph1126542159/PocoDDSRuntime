cmake_minimum_required(VERSION 3.24)
project(PocoDDSRuntimeComponentContractConsumer LANGUAGES CXX)

find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS ServiceDependencyCore)
include(CTest)

if(NOT EXISTS "${PocoDDSRuntime_PROCESS_FILE_LEASE_MODULE}")
    message(FATAL_ERROR "Installed process file lease SDK module is unavailable")
endif()

find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
set(team_contract_package_dir "${CMAKE_CURRENT_BINARY_DIR}/team-contract-packages")
file(MAKE_DIRECTORY "${team_contract_package_dir}")
set(team_contract_trust_dir "${team_contract_package_dir}/trust")
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/create_team_contract_trust_fixture.py"
        --output "${team_contract_trust_dir}"
    RESULT_VARIABLE team_contract_trust_fixture_result)
if(NOT team_contract_trust_fixture_result EQUAL 0)
    message(FATAL_ERROR "Team contract trust fixture creation failed")
endif()
set(team_contract_trust_policy
    "${team_contract_trust_dir}/team-contract-trust-policy.json")
file(SHA256 "${team_contract_trust_policy}" team_contract_trust_policy_sha256)
set(team_contract_impact_approval_policy
    "${team_contract_trust_dir}/team-contract-impact-approval-policy.json")
file(SHA256 "${team_contract_impact_approval_policy}"
    team_contract_impact_approval_policy_sha256)
set(team_contract_runner_trust_policy
    "${team_contract_trust_dir}/team-contract-runner-trust-policy.json")
file(SHA256 "${team_contract_runner_trust_policy}"
    team_contract_runner_trust_policy_sha256)
set(team_contract_gate_authorization_policy
    "${team_contract_trust_dir}/team-contract-gate-authorization-policy.json")
file(SHA256 "${team_contract_gate_authorization_policy}"
    team_contract_gate_authorization_policy_sha256)
set(team_contract_registry_access_policy
    "${team_contract_trust_dir}/team-contract-registry-access-policy.json")
file(SHA256 "${team_contract_registry_access_policy}"
    team_contract_registry_access_policy_sha256)
set(team_contract_registry_anchor_policy
    "${team_contract_trust_dir}/team-contract-registry-anchor-policy.json")
file(SHA256 "${team_contract_registry_anchor_policy}"
    team_contract_registry_anchor_policy_sha256)
set(team_contract_impact_report
    "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-upgrade-impact.json")
set(team_contract_impact_execution_evidence
    "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-impact-execution.json")
set(team_contract_impact_junit
    "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-impact-tests.xml")
set(team_contract_impact_approval
    "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-impact-team-workflow.approval.json")
set(team_contract_impact_gate_report
    "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-impact-gate.json")
set(team_contract_runner_attestation
    "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-runner-attestation.json")
set(team_contract_gate_authorization
    "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-gate-authorization.json")
set(team_contract_registry "${CMAKE_CURRENT_BINARY_DIR}/team-contract-registry")
set(team_contract_registry_resolution
    "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-registry-resolution.json")
set(team_contract_remote_registry_resolution
    "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-remote-registry-resolution.json")
set(team_contract_remote_registry_output
    "${CMAKE_CURRENT_BINARY_DIR}/resolved-remote-production-contracts")
set(team_contract_registry_anchor
    "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-registry-anchor.json")
set(team_contract_registry_anchor_verification
    "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-registry-anchor-verification.json")
set(consumer_contract_package "${team_contract_package_dir}/consumer.pdrcontracts")
set(provider_contract_package "${team_contract_package_dir}/provider.pdrcontracts")
set(candidate_provider_contract_package
    "${team_contract_package_dir}/provider-candidate.pdrcontracts")
set(team_contract_lock "${team_contract_package_dir}/team-contracts.lock.json")
set(candidate_team_contract_lock
    "${team_contract_package_dir}/team-contracts-candidate.lock.json")
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_TEST_TEAM_WORKFLOW_KEY=${team_contract_trust_dir}/team-workflow.private.pem"
        "${Python3_EXECUTABLE}" "${PocoDDSRuntime_TEAM_CONTRACT_PACKAGE_TOOL}"
        pack --package-id team.order-workflow --version 1.0.0 --owner team.workflow
        --source-date-epoch 1700000000
        --ed25519-private-key-environment PDR_TEST_TEAM_WORKFLOW_KEY
        --signing-key-id team-workflow-test-2026
        --input "service-contract=${CMAKE_CURRENT_SOURCE_DIR}/bundle/service-contracts.json"
        --input "participant-declaration=${CMAKE_CURRENT_SOURCE_DIR}/bundle/configuration-participants.json"
        --input "key-lifecycle=${CMAKE_CURRENT_SOURCE_DIR}/bundle/configuration-key-lifecycle.json"
        --output "${consumer_contract_package}" --force
    RESULT_VARIABLE consumer_contract_package_result)
if(NOT consumer_contract_package_result EQUAL 0)
    message(FATAL_ERROR "Consumer team contract package creation failed")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_TEST_TEAM_SCHEDULING_KEY=${team_contract_trust_dir}/team-scheduling.private.pem"
        "${Python3_EXECUTABLE}" "${PocoDDSRuntime_TEAM_CONTRACT_PACKAGE_TOOL}"
        pack --package-id team.scheduler --version 1.0.0 --owner team.scheduling
        --source-date-epoch 1700000000
        --ed25519-private-key-environment PDR_TEST_TEAM_SCHEDULING_KEY
        --signing-key-id team-scheduling-test-2026
        --input "service-contract=${CMAKE_CURRENT_SOURCE_DIR}/fixtures/scheduler.service-contracts.json"
        --output "${provider_contract_package}" --force
    RESULT_VARIABLE provider_contract_package_result)
if(NOT provider_contract_package_result EQUAL 0)
    message(FATAL_ERROR "Provider team contract package creation failed")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        "PDR_TEST_TEAM_SCHEDULING_KEY=${team_contract_trust_dir}/team-scheduling.private.pem"
        "${Python3_EXECUTABLE}" "${PocoDDSRuntime_TEAM_CONTRACT_PACKAGE_TOOL}"
        pack --package-id team.scheduler --version 1.1.0 --owner team.scheduling
        --source-date-epoch 1700000000
        --ed25519-private-key-environment PDR_TEST_TEAM_SCHEDULING_KEY
        --signing-key-id team-scheduling-test-2026
        --input
            "service-contract=${CMAKE_CURRENT_SOURCE_DIR}/fixtures/scheduler-candidate.service-contracts.json"
        --output "${candidate_provider_contract_package}" --force
    RESULT_VARIABLE candidate_provider_contract_package_result)
if(NOT candidate_provider_contract_package_result EQUAL 0)
    message(FATAL_ERROR "Candidate Provider team contract package creation failed")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${PocoDDSRuntime_TEAM_CONTRACT_PACKAGE_TOOL}"
        lock --package "${provider_contract_package}"
        --package "${consumer_contract_package}"
        --require-signature
        --trust-policy "${team_contract_trust_policy}"
        --expected-trust-policy-id component-consumer-team-contracts
        --expected-trust-policy-sha256 "${team_contract_trust_policy_sha256}"
        --verification-time 2026-08-25T12:00:00Z
        --output "${team_contract_lock}" --force
    RESULT_VARIABLE team_contract_lock_result)
if(NOT team_contract_lock_result EQUAL 0)
    message(FATAL_ERROR "Team contract package lock creation failed")
endif()
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${PocoDDSRuntime_TEAM_CONTRACT_PACKAGE_TOOL}"
        lock --package "${candidate_provider_contract_package}"
        --package "${consumer_contract_package}"
        --require-signature
        --trust-policy "${team_contract_trust_policy}"
        --expected-trust-policy-id component-consumer-team-contracts
        --expected-trust-policy-sha256 "${team_contract_trust_policy_sha256}"
        --verification-time 2026-08-25T12:00:00Z
        --output "${candidate_team_contract_lock}" --force
    RESULT_VARIABLE candidate_team_contract_lock_result)
if(NOT candidate_team_contract_lock_result EQUAL 0)
    message(FATAL_ERROR "Candidate team contract package lock creation failed")
endif()

pdr_add_team_contract_package_test(
    NAME team-contract-package-resolution
    LOCK "${team_contract_lock}"
    PACKAGES "${provider_contract_package}" "${consumer_contract_package}"
    REQUIRE_SIGNATURE
    TRUST_POLICY "${team_contract_trust_policy}"
    EXPECTED_TRUST_POLICY_ID component-consumer-team-contracts
    EXPECTED_TRUST_POLICY_SHA256 "${team_contract_trust_policy_sha256}"
    VERIFICATION_TIME 2026-08-25T12:00:00Z
    OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/resolved-team-contracts"
    REPORT "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-package-resolution.json")

pdr_add_team_contract_impact_test(
    NAME team-contract-upgrade-impact
    CURRENT_LOCK "${team_contract_lock}"
    CURRENT_PACKAGES "${provider_contract_package}" "${consumer_contract_package}"
    CANDIDATE_LOCK "${candidate_team_contract_lock}"
    CANDIDATE_PACKAGES
        "${candidate_provider_contract_package}" "${consumer_contract_package}"
    CONSUMER_CATALOG
        "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/team-contract-consumers.json"
    REQUIRE_SIGNATURE
    CURRENT_TRUST_POLICY "${team_contract_trust_policy}"
    CURRENT_EXPECTED_TRUST_POLICY_ID component-consumer-team-contracts
    CURRENT_EXPECTED_TRUST_POLICY_SHA256 "${team_contract_trust_policy_sha256}"
    CANDIDATE_TRUST_POLICY "${team_contract_trust_policy}"
    CANDIDATE_EXPECTED_TRUST_POLICY_ID component-consumer-team-contracts
    CANDIDATE_EXPECTED_TRUST_POLICY_SHA256 "${team_contract_trust_policy_sha256}"
    VERIFICATION_TIME 2026-08-25T12:00:00Z
    REPORT "${team_contract_impact_report}")

add_test(NAME team-contract-impact-pipeline-clean
    COMMAND "${CMAKE_COMMAND}" -E rm -rf
        "${team_contract_impact_approval}" "${team_contract_runner_attestation}"
        "${team_contract_gate_authorization}"
        "${team_contract_registry}" "${team_contract_registry_anchor}"
        "${team_contract_remote_registry_output}"
        "${team_contract_remote_registry_resolution}"
        "${CMAKE_CURRENT_BINARY_DIR}/team-contract-remote-control"
        "${team_contract_registry_anchor_verification}")
set_tests_properties(team-contract-impact-pipeline-clean PROPERTIES
    LABELS "team;contract;impact;fixture;isolated"
    FIXTURES_SETUP team-contract-impact-pipeline)
set_tests_properties(team-contract-upgrade-impact PROPERTIES
    FIXTURES_REQUIRED team-contract-impact-pipeline)

pdr_add_team_contract_impact_approval_test(
    NAME team-contract-impact-owner-approval
    IMPACT_REPORT "${team_contract_impact_report}"
    OWNER team.workflow
    APPROVER_ID workflow-contract-owner
    KEY_ID team-workflow-impact-approver-2026
    PRIVATE_KEY_ENVIRONMENT PDR_TEST_TEAM_WORKFLOW_IMPACT_APPROVAL_KEY
    ISSUED_AT 2026-08-25T12:00:00Z
    LIFETIME_SECONDS 3600
    OUTPUT "${team_contract_impact_approval}"
    DEPENDS team-contract-upgrade-impact)
set_tests_properties(team-contract-impact-owner-approval PROPERTIES
    ENVIRONMENT
        "PDR_TEST_TEAM_WORKFLOW_IMPACT_APPROVAL_KEY=${team_contract_trust_dir}/team-workflow-impact-approval.private.pem"
    FIXTURES_REQUIRED team-contract-impact-pipeline)

pdr_add_team_contract_impact_execution_test(
    NAME team-contract-impact-execution
    IMPACT_REPORT "${team_contract_impact_report}"
    EVIDENCE "${team_contract_impact_execution_evidence}"
    JUNIT "${team_contract_impact_junit}"
    CONFIG Release
    DEPENDS team-contract-upgrade-impact)
set_tests_properties(team-contract-impact-execution PROPERTIES
    FIXTURES_REQUIRED team-contract-impact-pipeline)

pdr_add_team_contract_runner_attestation_test(
    NAME team-contract-impact-runner-attestation
    IMPACT_REPORT "${team_contract_impact_report}"
    EXECUTION_EVIDENCE "${team_contract_impact_execution_evidence}"
    JUNIT "${team_contract_impact_junit}"
    RUNNER_ID ci.windows.release
    REPOSITORY pocodds/runtime
    SOURCE_REVISION 1111111111111111111111111111111111111111
    WORKFLOW team-contract-acceptance
    JOB_ID windows-release
    RUN_ID component-consumer-run-1001
    KEY_ID component-consumer-runner-2026
    PRIVATE_KEY_ENVIRONMENT PDR_TEST_TEAM_CONTRACT_RUNNER_KEY
    ISSUED_AT 2026-08-25T12:00:00Z
    LIFETIME_SECONDS 3600
    OUTPUT "${team_contract_runner_attestation}"
    DEPENDS team-contract-impact-execution)
set_tests_properties(team-contract-impact-runner-attestation PROPERTIES
    ENVIRONMENT
        "PDR_TEST_TEAM_CONTRACT_RUNNER_KEY=${team_contract_trust_dir}/team-contract-ci-runner.private.pem"
    FIXTURES_REQUIRED team-contract-impact-pipeline)

pdr_add_team_contract_impact_gate_test(
    NAME team-contract-impact-gate
    IMPACT_REPORT "${team_contract_impact_report}"
    EVIDENCE "${team_contract_impact_execution_evidence}"
    JUNIT "${team_contract_impact_junit}"
    CONFIG Release
    APPROVAL_POLICY "${team_contract_impact_approval_policy}"
    EXPECTED_APPROVAL_POLICY_ID component-consumer-impact-owners
    EXPECTED_APPROVAL_POLICY_SHA256
        "${team_contract_impact_approval_policy_sha256}"
    APPROVALS "${team_contract_impact_approval}"
    RUNNER_ATTESTATION "${team_contract_runner_attestation}"
    RUNNER_TRUST_POLICY "${team_contract_runner_trust_policy}"
    EXPECTED_RUNNER_TRUST_POLICY_ID component-consumer-ci-runners
    EXPECTED_RUNNER_TRUST_POLICY_SHA256
        "${team_contract_runner_trust_policy_sha256}"
    VERIFICATION_TIME 2026-08-25T12:30:00Z
    GATE_REPORT "${team_contract_impact_gate_report}"
    DEPENDS team-contract-impact-execution team-contract-impact-owner-approval
        team-contract-impact-runner-attestation)
set_tests_properties(team-contract-impact-gate PROPERTIES
    FIXTURES_REQUIRED team-contract-impact-pipeline)

pdr_add_team_contract_gate_authorization_test(
    NAME team-contract-impact-gate-authorization
    GATE_REPORT "${team_contract_impact_gate_report}"
    IMPACT_REPORT "${team_contract_impact_report}"
    EXECUTION_EVIDENCE "${team_contract_impact_execution_evidence}"
    JUNIT "${team_contract_impact_junit}"
    CONFIG Release
    APPROVAL_POLICY "${team_contract_impact_approval_policy}"
    EXPECTED_APPROVAL_POLICY_ID component-consumer-impact-owners
    EXPECTED_APPROVAL_POLICY_SHA256
        "${team_contract_impact_approval_policy_sha256}"
    APPROVALS "${team_contract_impact_approval}"
    RUNNER_ATTESTATION "${team_contract_runner_attestation}"
    RUNNER_TRUST_POLICY "${team_contract_runner_trust_policy}"
    EXPECTED_RUNNER_TRUST_POLICY_ID component-consumer-ci-runners
    EXPECTED_RUNNER_TRUST_POLICY_SHA256
        "${team_contract_runner_trust_policy_sha256}"
    REGISTRY_ID component-consumer-contracts
    CHANNELS staging production
    AUTHORIZATION_ID component-consumer-gate-authorization-0001
    AUTHORIZER_ID release.gate.service
    KEY_ID component-consumer-gate-authorizer-2026
    PRIVATE_KEY_ENVIRONMENT PDR_TEST_TEAM_CONTRACT_GATE_AUTHORIZER_KEY
    ISSUED_AT 2026-08-25T12:00:00Z
    LIFETIME_SECONDS 3600
    VERIFICATION_TIME 2026-08-25T12:30:00Z
    OUTPUT "${team_contract_gate_authorization}"
    DEPENDS team-contract-impact-gate)
set_tests_properties(team-contract-impact-gate-authorization PROPERTIES
    ENVIRONMENT
        "PDR_TEST_TEAM_CONTRACT_GATE_AUTHORIZER_KEY=${team_contract_trust_dir}/team-contract-gate-authorizer.private.pem"
    FIXTURES_REQUIRED team-contract-impact-pipeline)

set(team_contract_registry_trust_arguments
    --trust-policy "${team_contract_trust_policy}"
    --expected-trust-policy-id component-consumer-team-contracts
    --expected-trust-policy-sha256 "${team_contract_trust_policy_sha256}"
    --verification-time 2026-08-25T12:00:00Z)
add_test(NAME team-contract-registry-init
    COMMAND "${Python3_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_TOOL}"
        init --registry "${team_contract_registry}"
        --registry-id component-consumer-contracts
        --actor product-contract-admin --occurred-at 2026-08-25T12:00:00Z
        ${team_contract_registry_trust_arguments})
set_tests_properties(team-contract-registry-init PROPERTIES
    LABELS "team;contract;registry;fixture;security;isolated"
    FIXTURES_REQUIRED team-contract-impact-pipeline)

add_test(NAME team-contract-registry-publish-workflow
    COMMAND "${Python3_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_TOOL}"
        publish --registry "${team_contract_registry}"
        --package "${consumer_contract_package}"
        --actor team.workflow --occurred-at 2026-08-25T12:01:00Z
        ${team_contract_registry_trust_arguments})
set_tests_properties(team-contract-registry-publish-workflow PROPERTIES
    LABELS "team;contract;registry;publish;security;isolated"
    DEPENDS team-contract-registry-init
    FIXTURES_REQUIRED team-contract-impact-pipeline)

add_test(NAME team-contract-registry-publish-scheduler-current
    COMMAND "${Python3_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_TOOL}"
        publish --registry "${team_contract_registry}"
        --package "${provider_contract_package}"
        --actor team.scheduling --occurred-at 2026-08-25T12:02:00Z
        ${team_contract_registry_trust_arguments})
set_tests_properties(team-contract-registry-publish-scheduler-current PROPERTIES
    LABELS "team;contract;registry;publish;security;isolated"
    DEPENDS team-contract-registry-publish-workflow
    FIXTURES_REQUIRED team-contract-impact-pipeline)

add_test(NAME team-contract-registry-publish-scheduler-candidate
    COMMAND "${Python3_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_TOOL}"
        publish --registry "${team_contract_registry}"
        --package "${candidate_provider_contract_package}"
        --actor team.scheduling --occurred-at 2026-08-25T12:03:00Z
        ${team_contract_registry_trust_arguments})
set_tests_properties(team-contract-registry-publish-scheduler-candidate PROPERTIES
    LABELS "team;contract;registry;publish;security;isolated"
    DEPENDS team-contract-registry-publish-scheduler-current
    FIXTURES_REQUIRED team-contract-impact-pipeline)

add_test(NAME team-contract-registry-promote-dev
    COMMAND "${Python3_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_TOOL}"
        promote --registry "${team_contract_registry}" --channel dev
        --lock "${candidate_team_contract_lock}" --expected-generation 0
        --actor product-release-manager --occurred-at 2026-08-25T12:10:00Z
        ${team_contract_registry_trust_arguments})
set_tests_properties(team-contract-registry-promote-dev PROPERTIES
    LABELS "team;contract;registry;promotion;dev;security;isolated"
    DEPENDS team-contract-registry-publish-scheduler-candidate
    FIXTURES_REQUIRED team-contract-impact-pipeline)

add_test(NAME team-contract-registry-promote-staging
    COMMAND "${Python3_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_TOOL}"
        promote --registry "${team_contract_registry}" --channel staging
        --lock "${candidate_team_contract_lock}" --expected-generation 0
        --impact-gate "${team_contract_impact_gate_report}"
        --runner-attestation "${team_contract_runner_attestation}"
        --runner-trust-policy "${team_contract_runner_trust_policy}"
        --expected-runner-trust-policy-id component-consumer-ci-runners
        --expected-runner-trust-policy-sha256
            "${team_contract_runner_trust_policy_sha256}"
        --gate-authorization "${team_contract_gate_authorization}"
        --gate-authorization-policy "${team_contract_gate_authorization_policy}"
        --expected-gate-authorization-policy-id
            component-consumer-gate-authorizers
        --expected-gate-authorization-policy-sha256
            "${team_contract_gate_authorization_policy_sha256}"
        --actor product-release-manager --occurred-at 2026-08-25T12:20:00Z
        ${team_contract_registry_trust_arguments})
set_tests_properties(team-contract-registry-promote-staging PROPERTIES
    LABELS "team;contract;registry;promotion;staging;security;isolated"
    DEPENDS "team-contract-registry-promote-dev;team-contract-impact-gate-authorization"
    FIXTURES_REQUIRED team-contract-impact-pipeline)

add_test(NAME team-contract-registry-promote-production
    COMMAND "${Python3_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_TOOL}"
        promote --registry "${team_contract_registry}" --channel production
        --lock "${candidate_team_contract_lock}" --expected-generation 0
        --impact-gate "${team_contract_impact_gate_report}"
        --runner-attestation "${team_contract_runner_attestation}"
        --runner-trust-policy "${team_contract_runner_trust_policy}"
        --expected-runner-trust-policy-id component-consumer-ci-runners
        --expected-runner-trust-policy-sha256
            "${team_contract_runner_trust_policy_sha256}"
        --gate-authorization "${team_contract_gate_authorization}"
        --gate-authorization-policy "${team_contract_gate_authorization_policy}"
        --expected-gate-authorization-policy-id
            component-consumer-gate-authorizers
        --expected-gate-authorization-policy-sha256
            "${team_contract_gate_authorization_policy_sha256}"
        --actor product-release-manager --occurred-at 2026-08-25T12:30:00Z
        ${team_contract_registry_trust_arguments})
set_tests_properties(team-contract-registry-promote-production PROPERTIES
    LABELS "team;contract;registry;promotion;production;security;isolated"
    DEPENDS team-contract-registry-promote-staging
    FIXTURES_REQUIRED team-contract-impact-pipeline)

add_test(NAME team-contract-registry-remote-production-resolution
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/run_remote_registry_consumer.py"
        --python "${Python3_EXECUTABLE}"
        --pdr "${PocoDDSRuntime_PDR_TOOL}"
        --remote-tool "${PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_REMOTE_TOOL}"
        --registry "${team_contract_registry}"
        --access-policy "${team_contract_registry_access_policy}"
        --access-policy-sha256 "${team_contract_registry_access_policy_sha256}"
        --trust-policy "${team_contract_trust_policy}"
        --trust-policy-sha256 "${team_contract_trust_policy_sha256}"
        --runner-policy "${team_contract_runner_trust_policy}"
        --runner-policy-sha256 "${team_contract_runner_trust_policy_sha256}"
        --gate-policy "${team_contract_gate_authorization_policy}"
        --gate-policy-sha256 "${team_contract_gate_authorization_policy_sha256}"
        --output "${team_contract_remote_registry_output}"
        --report "${team_contract_remote_registry_resolution}"
        --control "${CMAKE_CURRENT_BINARY_DIR}/team-contract-remote-control")
set_tests_properties(team-contract-registry-remote-production-resolution PROPERTIES
    LABELS "team;contract;registry;remote;production;rbac;security;isolated"
    DEPENDS team-contract-registry-promote-production
    FIXTURES_REQUIRED team-contract-impact-pipeline
    TIMEOUT 30)

pdr_add_team_contract_registry_test(
    NAME team-contract-registry-production-resolution
    REGISTRY "${team_contract_registry}"
    CHANNEL production
    OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/resolved-production-contracts"
    REPORT "${team_contract_registry_resolution}"
    PACKAGE_REPORT
        "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-registry-package-resolution.json"
    TRUST_POLICY "${team_contract_trust_policy}"
    EXPECTED_TRUST_POLICY_ID component-consumer-team-contracts
    EXPECTED_TRUST_POLICY_SHA256 "${team_contract_trust_policy_sha256}"
    VERIFICATION_TIME 2026-08-25T12:30:00Z
    DEPENDS team-contract-registry-promote-production)
set_tests_properties(team-contract-registry-production-resolution PROPERTIES
    FIXTURES_REQUIRED team-contract-impact-pipeline)

add_test(NAME team-contract-registry-external-anchor
    COMMAND "${Python3_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL}"
        registry-anchor --registry "${team_contract_registry}"
        --anchor-id component-consumer-anchor-0001
        --anchor-service-id external.audit.service
        --key-id component-consumer-anchor-2026
        --private-key-environment PDR_TEST_TEAM_CONTRACT_ANCHOR_KEY
        --issued-at 2026-08-25T12:40:00Z
        --output "${team_contract_registry_anchor}"
        ${team_contract_registry_trust_arguments})
set_tests_properties(team-contract-registry-external-anchor PROPERTIES
    LABELS "team;contract;registry;anchor;signature;security;isolated"
    DEPENDS team-contract-registry-production-resolution
    ENVIRONMENT
        "PDR_TEST_TEAM_CONTRACT_ANCHOR_KEY=${team_contract_trust_dir}/team-contract-registry-anchor.private.pem"
    FIXTURES_REQUIRED team-contract-impact-pipeline)

pdr_add_team_contract_registry_anchor_verification_test(
    NAME team-contract-registry-external-anchor-verification
    REGISTRY "${team_contract_registry}"
    ANCHOR "${team_contract_registry_anchor}"
    ANCHOR_POLICY "${team_contract_registry_anchor_policy}"
    EXPECTED_ANCHOR_POLICY_ID component-consumer-registry-auditors
    EXPECTED_ANCHOR_POLICY_SHA256 "${team_contract_registry_anchor_policy_sha256}"
    TRUST_POLICY "${team_contract_trust_policy}"
    EXPECTED_TRUST_POLICY_ID component-consumer-team-contracts
    EXPECTED_TRUST_POLICY_SHA256 "${team_contract_trust_policy_sha256}"
    VERIFICATION_TIME 2026-08-25T12:45:00Z
    REPORT "${team_contract_registry_anchor_verification}"
    DEPENDS team-contract-registry-external-anchor)
set_tests_properties(team-contract-registry-external-anchor-verification PROPERTIES
    FIXTURES_REQUIRED team-contract-impact-pipeline)

pdr_add_component_contract_test(
    NAME order-workflow-contract
    COMPONENT "${CMAKE_CURRENT_SOURCE_DIR}/pdr-component.json"
    SERVICE_CONTRACT "${CMAKE_CURRENT_SOURCE_DIR}/bundle/service-contracts.json"
    PROVIDER_CONTRACTS
        "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/scheduler.service-contracts.json"
    LABELS service
    REPORT "${CMAKE_CURRENT_BINARY_DIR}/reports/order-workflow-contract.json")

pdr_add_configuration_participant_contract_test(
    NAME participant-compatibility-contract
    DECLARATION
        "${CMAKE_CURRENT_SOURCE_DIR}/bundle/configuration-participants.json"
    BASELINE
        "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/configuration-participant-baseline.json"
    REPORT
        "${CMAKE_CURRENT_BINARY_DIR}/reports/participant-compatibility-contract.json")

pdr_add_configuration_key_lifecycle_contract_test(
    NAME configuration-key-lifecycle-contract
    DECLARATION
        "${CMAKE_CURRENT_SOURCE_DIR}/bundle/configuration-key-lifecycle.json"
    PARTICIPANT_DECLARATION
        "${CMAKE_CURRENT_SOURCE_DIR}/bundle/configuration-participants.json"
    RUNTIME_VERSION "0.1.0"
    BASELINE
        "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/configuration-key-lifecycle-baseline.json"
    REPORT
        "${CMAKE_CURRENT_BINARY_DIR}/reports/configuration-key-lifecycle-contract.json")
