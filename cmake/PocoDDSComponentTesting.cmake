include_guard(GLOBAL)
include(CMakeParseArguments)

# Register a service-contract conformance test that runs without a Runtime
# process. Provider contracts are explicit test inputs, so the evidence is
# deterministic and can be owned by the consumer team.
function(pdr_add_component_contract_test)
    set(options)
    set(oneValueArgs NAME COMPONENT SERVICE_CONTRACT REPORT PYTHON_EXECUTABLE)
    set(multiValueArgs PROVIDER_CONTRACTS LABELS)
    cmake_parse_arguments(PDR_CONTRACT
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

    if(PDR_CONTRACT_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_component_contract_test received unknown arguments: "
            "${PDR_CONTRACT_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument NAME COMPONENT SERVICE_CONTRACT)
        if(NOT PDR_CONTRACT_${required_argument})
            message(FATAL_ERROR
                "pdr_add_component_contract_test requires ${required_argument}")
        endif()
    endforeach()
    if(NOT BUILD_TESTING)
        return()
    endif()

    if(NOT PDR_CONTRACT_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_CONTRACT_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PocoDDSRuntime_COMPONENT_CONTRACT_TEST_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_COMPONENT_CONTRACT_TEST_TOOL}")
        message(FATAL_ERROR
            "Installed component contract test tool is unavailable: "
            "${PocoDDSRuntime_COMPONENT_CONTRACT_TEST_TOOL}")
    endif()

    get_filename_component(component "${PDR_CONTRACT_COMPONENT}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    get_filename_component(service_contract "${PDR_CONTRACT_SERVICE_CONTRACT}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    foreach(required_file "${component}" "${service_contract}")
        if(NOT EXISTS "${required_file}")
            message(FATAL_ERROR "Component contract test input does not exist: ${required_file}")
        endif()
    endforeach()

    if(PDR_CONTRACT_REPORT)
        get_filename_component(report "${PDR_CONTRACT_REPORT}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    else()
        set(report
            "${CMAKE_CURRENT_BINARY_DIR}/reports/${PDR_CONTRACT_NAME}.json")
    endif()
    set(command
        "${PDR_CONTRACT_PYTHON_EXECUTABLE}"
        "${PocoDDSRuntime_COMPONENT_CONTRACT_TEST_TOOL}"
        "${component}"
        --service-contract "${service_contract}"
        --report "${report}")
    foreach(provider IN LISTS PDR_CONTRACT_PROVIDER_CONTRACTS)
        get_filename_component(provider_path "${provider}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${provider_path}")
            message(FATAL_ERROR
                "Provider service contract does not exist: ${provider_path}")
        endif()
        list(APPEND command --provider-contract "${provider_path}")
    endforeach()

    add_test(NAME "${PDR_CONTRACT_NAME}" COMMAND ${command})
    set(labels component contract conformance isolated)
    list(APPEND labels ${PDR_CONTRACT_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_CONTRACT_NAME}" PROPERTIES
        LABELS "${labels}"
        TIMEOUT 15)
endfunction()

# Compare two fully verified team-contract locks before a Consumer accepts the
# candidate. The report is both a compatibility gate and an affected-test plan.
function(pdr_add_team_contract_impact_test)
    set(options REQUIRE_SIGNATURE)
    set(oneValueArgs
        NAME CURRENT_LOCK CANDIDATE_LOCK CONSUMER_CATALOG REPORT PYTHON_EXECUTABLE
        CURRENT_TRUST_POLICY CURRENT_EXPECTED_TRUST_POLICY_ID
        CURRENT_EXPECTED_TRUST_POLICY_SHA256 CANDIDATE_TRUST_POLICY
        CANDIDATE_EXPECTED_TRUST_POLICY_ID CANDIDATE_EXPECTED_TRUST_POLICY_SHA256
        VERIFICATION_TIME)
    set(multiValueArgs CURRENT_PACKAGES CANDIDATE_PACKAGES LABELS)
    cmake_parse_arguments(PDR_TEAM_IMPACT
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})
    if(PDR_TEAM_IMPACT_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_team_contract_impact_test received unknown arguments: "
            "${PDR_TEAM_IMPACT_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument NAME CURRENT_LOCK CANDIDATE_LOCK CONSUMER_CATALOG REPORT)
        if(NOT PDR_TEAM_IMPACT_${required_argument})
            message(FATAL_ERROR
                "pdr_add_team_contract_impact_test requires ${required_argument}")
        endif()
    endforeach()
    if(NOT PDR_TEAM_IMPACT_CURRENT_PACKAGES OR NOT PDR_TEAM_IMPACT_CANDIDATE_PACKAGES)
        message(FATAL_ERROR
            "pdr_add_team_contract_impact_test requires current and candidate packages")
    endif()
    if(NOT BUILD_TESTING)
        return()
    endif()
    if(NOT PDR_TEAM_IMPACT_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_TEAM_IMPACT_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PocoDDSRuntime_TEAM_CONTRACT_IMPACT_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_TOOL}")
        message(FATAL_ERROR
            "Installed team contract impact tool is unavailable: "
            "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_TOOL}")
    endif()
    foreach(input CURRENT_LOCK CANDIDATE_LOCK CONSUMER_CATALOG)
        get_filename_component(input_path "${PDR_TEAM_IMPACT_${input}}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${input_path}")
            message(FATAL_ERROR "Team contract impact input does not exist: ${input_path}")
        endif()
        set(${input}_PATH "${input_path}")
    endforeach()
    get_filename_component(report "${PDR_TEAM_IMPACT_REPORT}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    set(command
        "${PDR_TEAM_IMPACT_PYTHON_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_TOOL}"
        --current-lock "${CURRENT_LOCK_PATH}"
        --candidate-lock "${CANDIDATE_LOCK_PATH}"
        --consumer-catalog "${CONSUMER_CATALOG_PATH}"
        --report "${report}")
    foreach(current_package IN LISTS PDR_TEAM_IMPACT_CURRENT_PACKAGES)
        get_filename_component(package_path "${current_package}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${package_path}")
            message(FATAL_ERROR "Current team contract package does not exist: ${package_path}")
        endif()
        list(APPEND command --current-package "${package_path}")
    endforeach()
    foreach(candidate_package IN LISTS PDR_TEAM_IMPACT_CANDIDATE_PACKAGES)
        get_filename_component(package_path "${candidate_package}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${package_path}")
            message(FATAL_ERROR "Candidate team contract package does not exist: ${package_path}")
        endif()
        list(APPEND command --candidate-package "${package_path}")
    endforeach()
    if(PDR_TEAM_IMPACT_REQUIRE_SIGNATURE)
        foreach(required_trust_argument
                CURRENT_TRUST_POLICY CURRENT_EXPECTED_TRUST_POLICY_ID
                CURRENT_EXPECTED_TRUST_POLICY_SHA256 CANDIDATE_TRUST_POLICY
                CANDIDATE_EXPECTED_TRUST_POLICY_ID
                CANDIDATE_EXPECTED_TRUST_POLICY_SHA256)
            if(NOT PDR_TEAM_IMPACT_${required_trust_argument})
                message(FATAL_ERROR
                    "Signed team contract impact test requires ${required_trust_argument}")
            endif()
        endforeach()
        get_filename_component(current_trust_policy
            "${PDR_TEAM_IMPACT_CURRENT_TRUST_POLICY}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        get_filename_component(candidate_trust_policy
            "${PDR_TEAM_IMPACT_CANDIDATE_TRUST_POLICY}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        foreach(policy_path "${current_trust_policy}" "${candidate_trust_policy}")
            if(NOT EXISTS "${policy_path}")
                message(FATAL_ERROR "Team contract impact trust policy is missing: ${policy_path}")
            endif()
        endforeach()
        list(APPEND command
            --require-signature
            --current-trust-policy "${current_trust_policy}"
            --current-expected-trust-policy-id
                "${PDR_TEAM_IMPACT_CURRENT_EXPECTED_TRUST_POLICY_ID}"
            --current-expected-trust-policy-sha256
                "${PDR_TEAM_IMPACT_CURRENT_EXPECTED_TRUST_POLICY_SHA256}"
            --candidate-trust-policy "${candidate_trust_policy}"
            --candidate-expected-trust-policy-id
                "${PDR_TEAM_IMPACT_CANDIDATE_EXPECTED_TRUST_POLICY_ID}"
            --candidate-expected-trust-policy-sha256
                "${PDR_TEAM_IMPACT_CANDIDATE_EXPECTED_TRUST_POLICY_SHA256}")
        if(PDR_TEAM_IMPACT_VERIFICATION_TIME)
            list(APPEND command --verification-time "${PDR_TEAM_IMPACT_VERIFICATION_TIME}")
        endif()
    endif()
    add_test(NAME "${PDR_TEAM_IMPACT_NAME}" COMMAND ${command})
    set(labels team contract package impact dependency conformance isolated)
    list(APPEND labels ${PDR_TEAM_IMPACT_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_TEAM_IMPACT_NAME}" PROPERTIES
        LABELS "${labels}" TIMEOUT 20)
endfunction()

# Execute exactly the CTest labels selected by a compatible team-contract
# impact report and persist both a content-bound evidence document and JUnit.
function(pdr_add_team_contract_impact_execution_test)
    set(options)
    set(oneValueArgs
        NAME IMPACT_REPORT EVIDENCE JUNIT CTEST_TEST_DIRECTORY CONFIG
        CTEST_EXECUTABLE PYTHON_EXECUTABLE)
    set(multiValueArgs DEPENDS LABELS)
    cmake_parse_arguments(PDR_TEAM_EXECUTION
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})
    if(PDR_TEAM_EXECUTION_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_team_contract_impact_execution_test received unknown arguments: "
            "${PDR_TEAM_EXECUTION_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument NAME IMPACT_REPORT EVIDENCE JUNIT)
        if(NOT PDR_TEAM_EXECUTION_${required_argument})
            message(FATAL_ERROR
                "pdr_add_team_contract_impact_execution_test requires ${required_argument}")
        endif()
    endforeach()
    if(NOT BUILD_TESTING)
        return()
    endif()
    if(NOT PDR_TEAM_EXECUTION_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_TEAM_EXECUTION_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PDR_TEAM_EXECUTION_CTEST_EXECUTABLE)
        set(PDR_TEAM_EXECUTION_CTEST_EXECUTABLE "${CMAKE_CTEST_COMMAND}")
    endif()
    if(NOT PDR_TEAM_EXECUTION_CTEST_TEST_DIRECTORY)
        set(PDR_TEAM_EXECUTION_CTEST_TEST_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}")
    endif()
    if(NOT PDR_TEAM_EXECUTION_CONFIG)
        set(PDR_TEAM_EXECUTION_CONFIG "Release")
    endif()
    if(NOT PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL}")
        message(FATAL_ERROR
            "Installed team contract impact gate tool is unavailable: "
            "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL}")
    endif()
    foreach(argument IMPACT_REPORT EVIDENCE JUNIT CTEST_TEST_DIRECTORY CTEST_EXECUTABLE)
        get_filename_component(${argument}_PATH "${PDR_TEAM_EXECUTION_${argument}}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    endforeach()
    add_test(NAME "${PDR_TEAM_EXECUTION_NAME}"
        COMMAND "${PDR_TEAM_EXECUTION_PYTHON_EXECUTABLE}"
            "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL}"
            execute --report "${IMPACT_REPORT_PATH}"
            --ctest "${CTEST_EXECUTABLE_PATH}"
            --test-dir "${CTEST_TEST_DIRECTORY_PATH}"
            --config "${PDR_TEAM_EXECUTION_CONFIG}"
            --evidence "${EVIDENCE_PATH}" --junit "${JUNIT_PATH}")
    set(labels team contract impact execution evidence security isolated)
    list(APPEND labels ${PDR_TEAM_EXECUTION_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_TEAM_EXECUTION_NAME}" PROPERTIES
        LABELS "${labels}" DEPENDS "${PDR_TEAM_EXECUTION_DEPENDS}"
        RUN_SERIAL TRUE TIMEOUT 120)
endfunction()

# Produce one short-lived signed approval for an affected Consumer Owner. The
# private key is referenced only through an inherited environment variable.
function(pdr_add_team_contract_impact_approval_test)
    set(options)
    set(oneValueArgs
        NAME IMPACT_REPORT OWNER APPROVER_ID KEY_ID PRIVATE_KEY_ENVIRONMENT
        PRIVATE_KEY_PASSPHRASE_ENVIRONMENT ISSUED_AT LIFETIME_SECONDS OUTPUT
        PYTHON_EXECUTABLE)
    set(multiValueArgs DEPENDS LABELS)
    cmake_parse_arguments(PDR_TEAM_APPROVAL
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})
    if(PDR_TEAM_APPROVAL_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_team_contract_impact_approval_test received unknown arguments: "
            "${PDR_TEAM_APPROVAL_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument
            NAME IMPACT_REPORT OWNER APPROVER_ID KEY_ID PRIVATE_KEY_ENVIRONMENT OUTPUT)
        if(NOT PDR_TEAM_APPROVAL_${required_argument})
            message(FATAL_ERROR
                "pdr_add_team_contract_impact_approval_test requires ${required_argument}")
        endif()
    endforeach()
    if(NOT BUILD_TESTING)
        return()
    endif()
    if(NOT PDR_TEAM_APPROVAL_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_TEAM_APPROVAL_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PDR_TEAM_APPROVAL_LIFETIME_SECONDS)
        set(PDR_TEAM_APPROVAL_LIFETIME_SECONDS 3600)
    endif()
    if(NOT PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL}")
        message(FATAL_ERROR
            "Installed team contract impact gate tool is unavailable: "
            "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL}")
    endif()
    get_filename_component(impact_report "${PDR_TEAM_APPROVAL_IMPACT_REPORT}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    get_filename_component(output "${PDR_TEAM_APPROVAL_OUTPUT}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    set(command
        "${PDR_TEAM_APPROVAL_PYTHON_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL}"
        approve --report "${impact_report}" --owner "${PDR_TEAM_APPROVAL_OWNER}"
        --approver-id "${PDR_TEAM_APPROVAL_APPROVER_ID}"
        --key-id "${PDR_TEAM_APPROVAL_KEY_ID}"
        --private-key-environment "${PDR_TEAM_APPROVAL_PRIVATE_KEY_ENVIRONMENT}"
        --lifetime-seconds "${PDR_TEAM_APPROVAL_LIFETIME_SECONDS}" --output "${output}")
    if(PDR_TEAM_APPROVAL_PRIVATE_KEY_PASSPHRASE_ENVIRONMENT)
        list(APPEND command --private-key-passphrase-environment
            "${PDR_TEAM_APPROVAL_PRIVATE_KEY_PASSPHRASE_ENVIRONMENT}")
    endif()
    if(PDR_TEAM_APPROVAL_ISSUED_AT)
        list(APPEND command --issued-at "${PDR_TEAM_APPROVAL_ISSUED_AT}")
    endif()
    add_test(NAME "${PDR_TEAM_APPROVAL_NAME}" COMMAND ${command})
    set(labels team contract impact approval signature security isolated)
    list(APPEND labels ${PDR_TEAM_APPROVAL_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_TEAM_APPROVAL_NAME}" PROPERTIES
        LABELS "${labels}" DEPENDS "${PDR_TEAM_APPROVAL_DEPENDS}" TIMEOUT 20)
endfunction()

# Sign exact impact execution evidence with a CI Runner key. The private key is
# referenced only by an inherited environment-variable name.
function(pdr_add_team_contract_runner_attestation_test)
    set(options)
    set(oneValueArgs
        NAME IMPACT_REPORT EXECUTION_EVIDENCE JUNIT RUNNER_ID REPOSITORY
        SOURCE_REVISION WORKFLOW JOB_ID RUN_ID KEY_ID PRIVATE_KEY_ENVIRONMENT
        PRIVATE_KEY_PASSPHRASE_ENVIRONMENT ISSUED_AT LIFETIME_SECONDS OUTPUT
        PYTHON_EXECUTABLE)
    set(multiValueArgs DEPENDS LABELS)
    cmake_parse_arguments(PDR_TEAM_RUNNER
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})
    if(PDR_TEAM_RUNNER_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_team_contract_runner_attestation_test received unknown arguments: "
            "${PDR_TEAM_RUNNER_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument
            NAME IMPACT_REPORT EXECUTION_EVIDENCE JUNIT RUNNER_ID REPOSITORY
            SOURCE_REVISION WORKFLOW JOB_ID RUN_ID KEY_ID PRIVATE_KEY_ENVIRONMENT OUTPUT)
        if(NOT PDR_TEAM_RUNNER_${required_argument})
            message(FATAL_ERROR
                "pdr_add_team_contract_runner_attestation_test requires ${required_argument}")
        endif()
    endforeach()
    if(NOT BUILD_TESTING)
        return()
    endif()
    if(NOT PDR_TEAM_RUNNER_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_TEAM_RUNNER_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PDR_TEAM_RUNNER_LIFETIME_SECONDS)
        set(PDR_TEAM_RUNNER_LIFETIME_SECONDS 3600)
    endif()
    if(NOT PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL}")
        message(FATAL_ERROR
            "Installed team contract provenance tool is unavailable: "
            "${PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL}")
    endif()
    foreach(argument IMPACT_REPORT EXECUTION_EVIDENCE JUNIT OUTPUT)
        get_filename_component(${argument}_PATH "${PDR_TEAM_RUNNER_${argument}}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    endforeach()
    set(command
        "${PDR_TEAM_RUNNER_PYTHON_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL}"
        runner-attest --report "${IMPACT_REPORT_PATH}"
        --evidence "${EXECUTION_EVIDENCE_PATH}" --junit "${JUNIT_PATH}"
        --runner-id "${PDR_TEAM_RUNNER_RUNNER_ID}"
        --repository "${PDR_TEAM_RUNNER_REPOSITORY}"
        --source-revision "${PDR_TEAM_RUNNER_SOURCE_REVISION}"
        --workflow "${PDR_TEAM_RUNNER_WORKFLOW}"
        --job-id "${PDR_TEAM_RUNNER_JOB_ID}" --run-id "${PDR_TEAM_RUNNER_RUN_ID}"
        --key-id "${PDR_TEAM_RUNNER_KEY_ID}"
        --private-key-environment "${PDR_TEAM_RUNNER_PRIVATE_KEY_ENVIRONMENT}"
        --lifetime-seconds "${PDR_TEAM_RUNNER_LIFETIME_SECONDS}"
        --output "${OUTPUT_PATH}")
    if(PDR_TEAM_RUNNER_PRIVATE_KEY_PASSPHRASE_ENVIRONMENT)
        list(APPEND command --private-key-passphrase-environment
            "${PDR_TEAM_RUNNER_PRIVATE_KEY_PASSPHRASE_ENVIRONMENT}")
    endif()
    if(PDR_TEAM_RUNNER_ISSUED_AT)
        list(APPEND command --issued-at "${PDR_TEAM_RUNNER_ISSUED_AT}")
    endif()
    add_test(NAME "${PDR_TEAM_RUNNER_NAME}" COMMAND ${command})
    set(labels team contract impact execution runner attestation signature security isolated)
    list(APPEND labels ${PDR_TEAM_RUNNER_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_TEAM_RUNNER_NAME}" PROPERTIES
        LABELS "${labels}" DEPENDS "${PDR_TEAM_RUNNER_DEPENDS}" TIMEOUT 20)
endfunction()

# Bind a compatible impact report to current CTest catalog/JUnit evidence and
# one distinct, trusted approval from every affected Consumer Owner.
function(pdr_add_team_contract_impact_gate_test)
    set(options)
    set(oneValueArgs
        NAME IMPACT_REPORT EVIDENCE JUNIT CTEST_TEST_DIRECTORY CONFIG
        CTEST_EXECUTABLE APPROVAL_POLICY EXPECTED_APPROVAL_POLICY_ID
        EXPECTED_APPROVAL_POLICY_SHA256 VERIFICATION_TIME GATE_REPORT
        RUNNER_ATTESTATION RUNNER_TRUST_POLICY EXPECTED_RUNNER_TRUST_POLICY_ID
        EXPECTED_RUNNER_TRUST_POLICY_SHA256 PYTHON_EXECUTABLE)
    set(multiValueArgs APPROVALS DEPENDS LABELS)
    cmake_parse_arguments(PDR_TEAM_GATE
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})
    if(PDR_TEAM_GATE_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_team_contract_impact_gate_test received unknown arguments: "
            "${PDR_TEAM_GATE_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument NAME IMPACT_REPORT EVIDENCE JUNIT GATE_REPORT)
        if(NOT PDR_TEAM_GATE_${required_argument})
            message(FATAL_ERROR
                "pdr_add_team_contract_impact_gate_test requires ${required_argument}")
        endif()
    endforeach()
    if(NOT BUILD_TESTING)
        return()
    endif()
    if(NOT PDR_TEAM_GATE_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_TEAM_GATE_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PDR_TEAM_GATE_CTEST_EXECUTABLE)
        set(PDR_TEAM_GATE_CTEST_EXECUTABLE "${CMAKE_CTEST_COMMAND}")
    endif()
    if(NOT PDR_TEAM_GATE_CTEST_TEST_DIRECTORY)
        set(PDR_TEAM_GATE_CTEST_TEST_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}")
    endif()
    if(NOT PDR_TEAM_GATE_CONFIG)
        set(PDR_TEAM_GATE_CONFIG "Release")
    endif()
    if(NOT PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL}")
        message(FATAL_ERROR
            "Installed team contract impact gate tool is unavailable: "
            "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL}")
    endif()
    foreach(argument IMPACT_REPORT EVIDENCE JUNIT CTEST_TEST_DIRECTORY CTEST_EXECUTABLE
                     GATE_REPORT)
        get_filename_component(${argument}_PATH "${PDR_TEAM_GATE_${argument}}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    endforeach()
    set(command
        "${PDR_TEAM_GATE_PYTHON_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_IMPACT_GATE_TOOL}"
        gate --report "${IMPACT_REPORT_PATH}" --evidence "${EVIDENCE_PATH}"
        --junit "${JUNIT_PATH}" --ctest "${CTEST_EXECUTABLE_PATH}"
        --test-dir "${CTEST_TEST_DIRECTORY_PATH}" --config "${PDR_TEAM_GATE_CONFIG}"
        --gate-report "${GATE_REPORT_PATH}")
    if(PDR_TEAM_GATE_APPROVAL_POLICY OR PDR_TEAM_GATE_APPROVALS)
        foreach(required_approval_argument
                APPROVAL_POLICY EXPECTED_APPROVAL_POLICY_ID
                EXPECTED_APPROVAL_POLICY_SHA256 VERIFICATION_TIME)
            if(NOT PDR_TEAM_GATE_${required_approval_argument})
                message(FATAL_ERROR
                    "Signed team contract impact gate requires ${required_approval_argument}")
            endif()
        endforeach()
        get_filename_component(approval_policy "${PDR_TEAM_GATE_APPROVAL_POLICY}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        list(APPEND command --approval-policy "${approval_policy}"
            --expected-approval-policy-id "${PDR_TEAM_GATE_EXPECTED_APPROVAL_POLICY_ID}"
            --expected-approval-policy-sha256
                "${PDR_TEAM_GATE_EXPECTED_APPROVAL_POLICY_SHA256}"
            --verification-time "${PDR_TEAM_GATE_VERIFICATION_TIME}")
        foreach(approval IN LISTS PDR_TEAM_GATE_APPROVALS)
            get_filename_component(approval_path "${approval}" ABSOLUTE
                BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
            list(APPEND command --approval "${approval_path}")
        endforeach()
    endif()
    if(PDR_TEAM_GATE_RUNNER_ATTESTATION OR PDR_TEAM_GATE_RUNNER_TRUST_POLICY)
        foreach(required_runner_argument
                RUNNER_ATTESTATION RUNNER_TRUST_POLICY EXPECTED_RUNNER_TRUST_POLICY_ID
                EXPECTED_RUNNER_TRUST_POLICY_SHA256)
            if(NOT PDR_TEAM_GATE_${required_runner_argument})
                message(FATAL_ERROR
                    "Runner-attested team contract impact gate requires "
                    "${required_runner_argument}")
            endif()
        endforeach()
        get_filename_component(runner_attestation
            "${PDR_TEAM_GATE_RUNNER_ATTESTATION}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
        get_filename_component(runner_trust_policy
            "${PDR_TEAM_GATE_RUNNER_TRUST_POLICY}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        list(APPEND command
            --runner-attestation "${runner_attestation}"
            --runner-trust-policy "${runner_trust_policy}"
            --expected-runner-trust-policy-id
                "${PDR_TEAM_GATE_EXPECTED_RUNNER_TRUST_POLICY_ID}"
            --expected-runner-trust-policy-sha256
                "${PDR_TEAM_GATE_EXPECTED_RUNNER_TRUST_POLICY_SHA256}")
    endif()
    add_test(NAME "${PDR_TEAM_GATE_NAME}" COMMAND ${command})
    set(labels team contract impact gate execution evidence approval security isolated)
    list(APPEND labels ${PDR_TEAM_GATE_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_TEAM_GATE_NAME}" PROPERTIES
        LABELS "${labels}" DEPENDS "${PDR_TEAM_GATE_DEPENDS}"
        RUN_SERIAL TRUE TIMEOUT 30)
endfunction()

# Re-run the complete Gate and sign its exact bytes for one Registry/channel set.
function(pdr_add_team_contract_gate_authorization_test)
    set(options)
    set(oneValueArgs
        NAME GATE_REPORT IMPACT_REPORT EXECUTION_EVIDENCE JUNIT CTEST_TEST_DIRECTORY
        CONFIG CTEST_EXECUTABLE APPROVAL_POLICY EXPECTED_APPROVAL_POLICY_ID
        EXPECTED_APPROVAL_POLICY_SHA256 RUNNER_ATTESTATION RUNNER_TRUST_POLICY
        EXPECTED_RUNNER_TRUST_POLICY_ID EXPECTED_RUNNER_TRUST_POLICY_SHA256
        REGISTRY_ID AUTHORIZATION_ID AUTHORIZER_ID KEY_ID PRIVATE_KEY_ENVIRONMENT
        PRIVATE_KEY_PASSPHRASE_ENVIRONMENT ISSUED_AT LIFETIME_SECONDS OUTPUT
        VERIFICATION_TIME PYTHON_EXECUTABLE)
    set(multiValueArgs CHANNELS APPROVALS DEPENDS LABELS)
    cmake_parse_arguments(PDR_TEAM_AUTH
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})
    if(PDR_TEAM_AUTH_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_team_contract_gate_authorization_test received unknown arguments: "
            "${PDR_TEAM_AUTH_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument
            NAME GATE_REPORT IMPACT_REPORT EXECUTION_EVIDENCE JUNIT REGISTRY_ID
            AUTHORIZATION_ID AUTHORIZER_ID KEY_ID PRIVATE_KEY_ENVIRONMENT OUTPUT)
        if(NOT PDR_TEAM_AUTH_${required_argument})
            message(FATAL_ERROR
                "pdr_add_team_contract_gate_authorization_test requires ${required_argument}")
        endif()
    endforeach()
    if(NOT PDR_TEAM_AUTH_CHANNELS)
        message(FATAL_ERROR
            "pdr_add_team_contract_gate_authorization_test requires CHANNELS")
    endif()
    if(NOT BUILD_TESTING)
        return()
    endif()
    if(NOT PDR_TEAM_AUTH_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_TEAM_AUTH_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PDR_TEAM_AUTH_CTEST_EXECUTABLE)
        set(PDR_TEAM_AUTH_CTEST_EXECUTABLE "${CMAKE_CTEST_COMMAND}")
    endif()
    if(NOT PDR_TEAM_AUTH_CTEST_TEST_DIRECTORY)
        set(PDR_TEAM_AUTH_CTEST_TEST_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}")
    endif()
    if(NOT PDR_TEAM_AUTH_CONFIG)
        set(PDR_TEAM_AUTH_CONFIG "Release")
    endif()
    if(NOT PDR_TEAM_AUTH_LIFETIME_SECONDS)
        set(PDR_TEAM_AUTH_LIFETIME_SECONDS 3600)
    endif()
    if(NOT PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL}")
        message(FATAL_ERROR
            "Installed team contract provenance tool is unavailable: "
            "${PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL}")
    endif()
    foreach(argument GATE_REPORT IMPACT_REPORT EXECUTION_EVIDENCE JUNIT
                     CTEST_TEST_DIRECTORY CTEST_EXECUTABLE OUTPUT)
        get_filename_component(${argument}_PATH "${PDR_TEAM_AUTH_${argument}}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    endforeach()
    set(command
        "${PDR_TEAM_AUTH_PYTHON_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL}"
        gate-authorize --gate-report "${GATE_REPORT_PATH}"
        --report "${IMPACT_REPORT_PATH}" --evidence "${EXECUTION_EVIDENCE_PATH}"
        --junit "${JUNIT_PATH}" --ctest "${CTEST_EXECUTABLE_PATH}"
        --test-dir "${CTEST_TEST_DIRECTORY_PATH}" --config "${PDR_TEAM_AUTH_CONFIG}"
        --registry-id "${PDR_TEAM_AUTH_REGISTRY_ID}"
        --authorization-id "${PDR_TEAM_AUTH_AUTHORIZATION_ID}"
        --authorizer-id "${PDR_TEAM_AUTH_AUTHORIZER_ID}"
        --key-id "${PDR_TEAM_AUTH_KEY_ID}"
        --private-key-environment "${PDR_TEAM_AUTH_PRIVATE_KEY_ENVIRONMENT}"
        --lifetime-seconds "${PDR_TEAM_AUTH_LIFETIME_SECONDS}"
        --output "${OUTPUT_PATH}")
    foreach(channel IN LISTS PDR_TEAM_AUTH_CHANNELS)
        list(APPEND command --channel "${channel}")
    endforeach()
    if(PDR_TEAM_AUTH_APPROVAL_POLICY OR PDR_TEAM_AUTH_APPROVALS)
        foreach(required_argument APPROVAL_POLICY EXPECTED_APPROVAL_POLICY_ID
                EXPECTED_APPROVAL_POLICY_SHA256 VERIFICATION_TIME)
            if(NOT PDR_TEAM_AUTH_${required_argument})
                message(FATAL_ERROR
                    "Gate authorization with approvals requires ${required_argument}")
            endif()
        endforeach()
        get_filename_component(approval_policy "${PDR_TEAM_AUTH_APPROVAL_POLICY}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        list(APPEND command --approval-policy "${approval_policy}"
            --expected-approval-policy-id "${PDR_TEAM_AUTH_EXPECTED_APPROVAL_POLICY_ID}"
            --expected-approval-policy-sha256
                "${PDR_TEAM_AUTH_EXPECTED_APPROVAL_POLICY_SHA256}"
            --verification-time "${PDR_TEAM_AUTH_VERIFICATION_TIME}")
        foreach(approval IN LISTS PDR_TEAM_AUTH_APPROVALS)
            get_filename_component(approval_path "${approval}" ABSOLUTE
                BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
            list(APPEND command --approval "${approval_path}")
        endforeach()
    elseif(PDR_TEAM_AUTH_VERIFICATION_TIME)
        list(APPEND command --verification-time "${PDR_TEAM_AUTH_VERIFICATION_TIME}")
    endif()
    if(PDR_TEAM_AUTH_RUNNER_ATTESTATION OR PDR_TEAM_AUTH_RUNNER_TRUST_POLICY)
        foreach(required_argument RUNNER_ATTESTATION RUNNER_TRUST_POLICY
                EXPECTED_RUNNER_TRUST_POLICY_ID EXPECTED_RUNNER_TRUST_POLICY_SHA256)
            if(NOT PDR_TEAM_AUTH_${required_argument})
                message(FATAL_ERROR
                    "Gate authorization with Runner evidence requires ${required_argument}")
            endif()
        endforeach()
        get_filename_component(runner_attestation "${PDR_TEAM_AUTH_RUNNER_ATTESTATION}"
            ABSOLUTE BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
        get_filename_component(runner_policy "${PDR_TEAM_AUTH_RUNNER_TRUST_POLICY}"
            ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        list(APPEND command --runner-attestation "${runner_attestation}"
            --runner-trust-policy "${runner_policy}"
            --expected-runner-trust-policy-id
                "${PDR_TEAM_AUTH_EXPECTED_RUNNER_TRUST_POLICY_ID}"
            --expected-runner-trust-policy-sha256
                "${PDR_TEAM_AUTH_EXPECTED_RUNNER_TRUST_POLICY_SHA256}")
    endif()
    if(PDR_TEAM_AUTH_PRIVATE_KEY_PASSPHRASE_ENVIRONMENT)
        list(APPEND command --private-key-passphrase-environment
            "${PDR_TEAM_AUTH_PRIVATE_KEY_PASSPHRASE_ENVIRONMENT}")
    endif()
    if(PDR_TEAM_AUTH_ISSUED_AT)
        list(APPEND command --issued-at "${PDR_TEAM_AUTH_ISSUED_AT}")
    endif()
    add_test(NAME "${PDR_TEAM_AUTH_NAME}" COMMAND ${command})
    set(labels team contract impact gate authorization signature security isolated)
    list(APPEND labels ${PDR_TEAM_AUTH_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_TEAM_AUTH_NAME}" PROPERTIES
        LABELS "${labels}" DEPENDS "${PDR_TEAM_AUTH_DEPENDS}"
        RUN_SERIAL TRUE TIMEOUT 40)
endfunction()

# Resolve one promoted team-contract Registry channel using only the Registry,
# channel name and pinned trust policy. No Provider workspace path is consumed.
function(pdr_add_team_contract_registry_test)
    set(options)
    set(oneValueArgs
        NAME REGISTRY CHANNEL OUTPUT_DIRECTORY REPORT PACKAGE_REPORT
        TRUST_POLICY EXPECTED_TRUST_POLICY_ID EXPECTED_TRUST_POLICY_SHA256
        VERIFICATION_TIME PYTHON_EXECUTABLE)
    set(multiValueArgs DEPENDS LABELS)
    cmake_parse_arguments(PDR_TEAM_REGISTRY
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})
    if(PDR_TEAM_REGISTRY_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_team_contract_registry_test received unknown arguments: "
            "${PDR_TEAM_REGISTRY_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument
            NAME REGISTRY CHANNEL OUTPUT_DIRECTORY REPORT TRUST_POLICY
            EXPECTED_TRUST_POLICY_ID EXPECTED_TRUST_POLICY_SHA256)
        if(NOT PDR_TEAM_REGISTRY_${required_argument})
            message(FATAL_ERROR
                "pdr_add_team_contract_registry_test requires ${required_argument}")
        endif()
    endforeach()
    if(NOT BUILD_TESTING)
        return()
    endif()
    if(NOT PDR_TEAM_REGISTRY_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_TEAM_REGISTRY_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_TOOL}")
        message(FATAL_ERROR
            "Installed team contract Registry tool is unavailable: "
            "${PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_TOOL}")
    endif()
    foreach(argument REGISTRY OUTPUT_DIRECTORY REPORT TRUST_POLICY)
        get_filename_component(${argument}_PATH "${PDR_TEAM_REGISTRY_${argument}}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    endforeach()
    set(command
        "${PDR_TEAM_REGISTRY_PYTHON_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_REGISTRY_TOOL}"
        resolve --registry "${REGISTRY_PATH}" --channel "${PDR_TEAM_REGISTRY_CHANNEL}"
        --output "${OUTPUT_DIRECTORY_PATH}" --report "${REPORT_PATH}"
        --trust-policy "${TRUST_POLICY_PATH}"
        --expected-trust-policy-id "${PDR_TEAM_REGISTRY_EXPECTED_TRUST_POLICY_ID}"
        --expected-trust-policy-sha256
            "${PDR_TEAM_REGISTRY_EXPECTED_TRUST_POLICY_SHA256}")
    if(PDR_TEAM_REGISTRY_PACKAGE_REPORT)
        get_filename_component(package_report "${PDR_TEAM_REGISTRY_PACKAGE_REPORT}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
        list(APPEND command --package-report "${package_report}")
    endif()
    if(PDR_TEAM_REGISTRY_VERIFICATION_TIME)
        list(APPEND command --verification-time "${PDR_TEAM_REGISTRY_VERIFICATION_TIME}")
    endif()
    add_test(NAME "${PDR_TEAM_REGISTRY_NAME}" COMMAND ${command})
    set(labels team contract registry channel promotion dependency conformance isolated)
    list(APPEND labels ${PDR_TEAM_REGISTRY_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_TEAM_REGISTRY_NAME}" PROPERTIES
        LABELS "${labels}" DEPENDS "${PDR_TEAM_REGISTRY_DEPENDS}"
        RUN_SERIAL TRUE TIMEOUT 60)
endfunction()

# Verify that the current Registry still contains an externally signed state
# anchor. Anchor creation belongs to an independent audit service, not CMake.
function(pdr_add_team_contract_registry_anchor_verification_test)
    set(options)
    set(oneValueArgs
        NAME REGISTRY ANCHOR ANCHOR_POLICY EXPECTED_ANCHOR_POLICY_ID
        EXPECTED_ANCHOR_POLICY_SHA256 TRUST_POLICY EXPECTED_TRUST_POLICY_ID
        EXPECTED_TRUST_POLICY_SHA256 VERIFICATION_TIME REPORT PYTHON_EXECUTABLE)
    set(multiValueArgs DEPENDS LABELS)
    cmake_parse_arguments(PDR_TEAM_ANCHOR
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})
    if(PDR_TEAM_ANCHOR_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_team_contract_registry_anchor_verification_test received "
            "unknown arguments: ${PDR_TEAM_ANCHOR_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument
            NAME REGISTRY ANCHOR ANCHOR_POLICY EXPECTED_ANCHOR_POLICY_ID
            EXPECTED_ANCHOR_POLICY_SHA256 TRUST_POLICY EXPECTED_TRUST_POLICY_ID
            EXPECTED_TRUST_POLICY_SHA256 REPORT)
        if(NOT PDR_TEAM_ANCHOR_${required_argument})
            message(FATAL_ERROR
                "pdr_add_team_contract_registry_anchor_verification_test requires "
                "${required_argument}")
        endif()
    endforeach()
    if(NOT BUILD_TESTING)
        return()
    endif()
    if(NOT PDR_TEAM_ANCHOR_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_TEAM_ANCHOR_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL}")
        message(FATAL_ERROR
            "Installed team contract provenance tool is unavailable: "
            "${PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL}")
    endif()
    foreach(argument REGISTRY ANCHOR ANCHOR_POLICY TRUST_POLICY REPORT)
        get_filename_component(${argument}_PATH "${PDR_TEAM_ANCHOR_${argument}}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    endforeach()
    set(command
        "${PDR_TEAM_ANCHOR_PYTHON_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_PROVENANCE_TOOL}"
        registry-anchor-verify --registry "${REGISTRY_PATH}" --anchor "${ANCHOR_PATH}"
        --anchor-policy "${ANCHOR_POLICY_PATH}"
        --expected-anchor-policy-id "${PDR_TEAM_ANCHOR_EXPECTED_ANCHOR_POLICY_ID}"
        --expected-anchor-policy-sha256
            "${PDR_TEAM_ANCHOR_EXPECTED_ANCHOR_POLICY_SHA256}"
        --trust-policy "${TRUST_POLICY_PATH}"
        --expected-trust-policy-id "${PDR_TEAM_ANCHOR_EXPECTED_TRUST_POLICY_ID}"
        --expected-trust-policy-sha256 "${PDR_TEAM_ANCHOR_EXPECTED_TRUST_POLICY_SHA256}"
        --verification-report "${REPORT_PATH}")
    if(PDR_TEAM_ANCHOR_VERIFICATION_TIME)
        list(APPEND command --verification-time "${PDR_TEAM_ANCHOR_VERIFICATION_TIME}")
    endif()
    add_test(NAME "${PDR_TEAM_ANCHOR_NAME}" COMMAND ${command})
    set(labels team contract registry anchor rollback security conformance isolated)
    list(APPEND labels ${PDR_TEAM_ANCHOR_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_TEAM_ANCHOR_NAME}" PROPERTIES
        LABELS "${labels}" DEPENDS "${PDR_TEAM_ANCHOR_DEPENDS}"
        RUN_SERIAL TRUE TIMEOUT 60)
endfunction()

# Resolve exact, content-addressed team contract packages in an isolated CTest.
# The lock intentionally contains no source path; PACKAGES may therefore come
# from any repository/cache location as long as every identity and digest is exact.
function(pdr_add_team_contract_package_test)
    set(options REQUIRE_SIGNATURE)
    set(oneValueArgs
        NAME LOCK OUTPUT_DIRECTORY REPORT PYTHON_EXECUTABLE TRUST_POLICY
        EXPECTED_TRUST_POLICY_ID EXPECTED_TRUST_POLICY_SHA256 VERIFICATION_TIME)
    set(multiValueArgs PACKAGES LABELS)
    cmake_parse_arguments(PDR_TEAM_CONTRACT
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

    if(PDR_TEAM_CONTRACT_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_team_contract_package_test received unknown arguments: "
            "${PDR_TEAM_CONTRACT_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument NAME LOCK OUTPUT_DIRECTORY)
        if(NOT PDR_TEAM_CONTRACT_${required_argument})
            message(FATAL_ERROR
                "pdr_add_team_contract_package_test requires ${required_argument}")
        endif()
    endforeach()
    if(NOT PDR_TEAM_CONTRACT_PACKAGES)
        message(FATAL_ERROR
            "pdr_add_team_contract_package_test requires at least one package")
    endif()
    if(NOT BUILD_TESTING)
        return()
    endif()
    if(NOT PDR_TEAM_CONTRACT_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_TEAM_CONTRACT_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PocoDDSRuntime_TEAM_CONTRACT_PACKAGE_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_TEAM_CONTRACT_PACKAGE_TOOL}")
        message(FATAL_ERROR
            "Installed team contract package tool is unavailable: "
            "${PocoDDSRuntime_TEAM_CONTRACT_PACKAGE_TOOL}")
    endif()
    get_filename_component(lock "${PDR_TEAM_CONTRACT_LOCK}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    if(NOT EXISTS "${lock}")
        message(FATAL_ERROR "Team contract package lock does not exist: ${lock}")
    endif()
    get_filename_component(output "${PDR_TEAM_CONTRACT_OUTPUT_DIRECTORY}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    if(PDR_TEAM_CONTRACT_REPORT)
        get_filename_component(report "${PDR_TEAM_CONTRACT_REPORT}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    else()
        set(report "${CMAKE_CURRENT_BINARY_DIR}/reports/${PDR_TEAM_CONTRACT_NAME}.json")
    endif()
    set(command
        "${PDR_TEAM_CONTRACT_PYTHON_EXECUTABLE}"
        "${PocoDDSRuntime_TEAM_CONTRACT_PACKAGE_TOOL}"
        resolve --lock "${lock}" --output "${output}" --report "${report}")
    if(PDR_TEAM_CONTRACT_REQUIRE_SIGNATURE OR PDR_TEAM_CONTRACT_TRUST_POLICY)
        foreach(required_trust_argument
                TRUST_POLICY EXPECTED_TRUST_POLICY_ID EXPECTED_TRUST_POLICY_SHA256)
            if(NOT PDR_TEAM_CONTRACT_${required_trust_argument})
                message(FATAL_ERROR
                    "Signed team contract package test requires ${required_trust_argument}")
            endif()
        endforeach()
        get_filename_component(trust_policy "${PDR_TEAM_CONTRACT_TRUST_POLICY}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${trust_policy}")
            message(FATAL_ERROR "Team contract trust policy does not exist: ${trust_policy}")
        endif()
        list(APPEND command
            --require-signature
            --trust-policy "${trust_policy}"
            --expected-trust-policy-id "${PDR_TEAM_CONTRACT_EXPECTED_TRUST_POLICY_ID}"
            --expected-trust-policy-sha256
                "${PDR_TEAM_CONTRACT_EXPECTED_TRUST_POLICY_SHA256}")
        if(PDR_TEAM_CONTRACT_VERIFICATION_TIME)
            list(APPEND command --verification-time
                "${PDR_TEAM_CONTRACT_VERIFICATION_TIME}")
        endif()
    endif()
    foreach(package IN LISTS PDR_TEAM_CONTRACT_PACKAGES)
        get_filename_component(package_path "${package}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${package_path}")
            message(FATAL_ERROR "Team contract package does not exist: ${package_path}")
        endif()
        list(APPEND command --package "${package_path}")
    endforeach()
    add_test(NAME "${PDR_TEAM_CONTRACT_NAME}" COMMAND ${command})
    set(labels team contract package lock dependency conformance isolated)
    list(APPEND labels ${PDR_TEAM_CONTRACT_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_TEAM_CONTRACT_NAME}" PROPERTIES
        LABELS "${labels}" TIMEOUT 15)
endfunction()

# Validate a Bundle-owned key lifecycle and, when supplied, product migration
# documents against explicit participant ownership. This is isolated from the
# Runtime so a product team can pin provider declarations by content in CI.
function(pdr_add_configuration_key_lifecycle_contract_test)
    set(options)
    set(oneValueArgs
        NAME DECLARATION PARTICIPANT_DECLARATION RUNTIME_VERSION BASELINE REPORT
        PYTHON_EXECUTABLE)
    set(multiValueArgs
        PROVIDER_DECLARATIONS PARTICIPANT_DECLARATIONS MIGRATIONS LABELS)
    cmake_parse_arguments(PDR_LIFECYCLE
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

    if(PDR_LIFECYCLE_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_configuration_key_lifecycle_contract_test received unknown arguments: "
            "${PDR_LIFECYCLE_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument NAME DECLARATION PARTICIPANT_DECLARATION RUNTIME_VERSION)
        if(NOT PDR_LIFECYCLE_${required_argument})
            message(FATAL_ERROR
                "pdr_add_configuration_key_lifecycle_contract_test requires ${required_argument}")
        endif()
    endforeach()
    if(NOT BUILD_TESTING)
        return()
    endif()
    if(NOT PDR_LIFECYCLE_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_LIFECYCLE_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PocoDDSRuntime_CONFIGURATION_KEY_LIFECYCLE_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_CONFIGURATION_KEY_LIFECYCLE_TOOL}")
        message(FATAL_ERROR
            "Installed configuration key lifecycle tool is unavailable: "
            "${PocoDDSRuntime_CONFIGURATION_KEY_LIFECYCLE_TOOL}")
    endif()
    get_filename_component(declaration "${PDR_LIFECYCLE_DECLARATION}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    get_filename_component(participant "${PDR_LIFECYCLE_PARTICIPANT_DECLARATION}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    foreach(required_file "${declaration}" "${participant}")
        if(NOT EXISTS "${required_file}")
            message(FATAL_ERROR
                "Configuration key lifecycle test input does not exist: ${required_file}")
        endif()
    endforeach()
    if(PDR_LIFECYCLE_REPORT)
        get_filename_component(report "${PDR_LIFECYCLE_REPORT}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    else()
        set(report "${CMAKE_CURRENT_BINARY_DIR}/reports/${PDR_LIFECYCLE_NAME}.json")
    endif()
    set(command
        "${PDR_LIFECYCLE_PYTHON_EXECUTABLE}"
        "${PocoDDSRuntime_CONFIGURATION_KEY_LIFECYCLE_TOOL}"
        --declaration "${declaration}"
        --participant-declaration "${participant}"
        --runtime-version "${PDR_LIFECYCLE_RUNTIME_VERSION}"
        --report "${report}")
    foreach(provider IN LISTS PDR_LIFECYCLE_PROVIDER_DECLARATIONS)
        get_filename_component(provider_path "${provider}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${provider_path}")
            message(FATAL_ERROR
                "Provider key lifecycle declaration does not exist: ${provider_path}")
        endif()
        list(APPEND command --declaration "${provider_path}")
    endforeach()
    foreach(provider IN LISTS PDR_LIFECYCLE_PARTICIPANT_DECLARATIONS)
        get_filename_component(provider_path "${provider}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${provider_path}")
            message(FATAL_ERROR
                "Provider participant declaration does not exist: ${provider_path}")
        endif()
        list(APPEND command --participant-declaration "${provider_path}")
    endforeach()
    foreach(migration IN LISTS PDR_LIFECYCLE_MIGRATIONS)
        get_filename_component(migration_path "${migration}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${migration_path}")
            message(FATAL_ERROR
                "Configuration migration does not exist: ${migration_path}")
        endif()
        list(APPEND command --migration "${migration_path}")
    endforeach()
    if(PDR_LIFECYCLE_BASELINE)
        get_filename_component(baseline "${PDR_LIFECYCLE_BASELINE}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${baseline}")
            message(FATAL_ERROR
                "Configuration key lifecycle baseline does not exist: ${baseline}")
        endif()
        list(APPEND command --baseline "${baseline}")
    endif()
    add_test(NAME "${PDR_LIFECYCLE_NAME}" COMMAND ${command})
    set(labels
        configuration migration deprecation ownership contract conformance isolated)
    list(APPEND labels ${PDR_LIFECYCLE_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_LIFECYCLE_NAME}" PROPERTIES
        LABELS "${labels}" TIMEOUT 15)
endfunction()

# Validate one Bundle's configuration-participant declaration together with
# declarations supplied by collaborating provider teams. This runs without a
# Runtime process and catches duplicate IDs/services, ownership-prefix overlap
# and dependency cycles before integration.
function(pdr_add_configuration_participant_contract_test)
    set(options)
    set(oneValueArgs NAME DECLARATION BASELINE REPORT PYTHON_EXECUTABLE)
    set(multiValueArgs PROVIDER_DECLARATIONS LABELS)
    cmake_parse_arguments(PDR_PARTICIPANT
        "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

    if(PDR_PARTICIPANT_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "pdr_add_configuration_participant_contract_test received unknown arguments: "
            "${PDR_PARTICIPANT_UNPARSED_ARGUMENTS}")
    endif()
    foreach(required_argument NAME DECLARATION)
        if(NOT PDR_PARTICIPANT_${required_argument})
            message(FATAL_ERROR
                "pdr_add_configuration_participant_contract_test requires ${required_argument}")
        endif()
    endforeach()
    if(NOT BUILD_TESTING)
        return()
    endif()

    if(NOT PDR_PARTICIPANT_PYTHON_EXECUTABLE)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        set(PDR_PARTICIPANT_PYTHON_EXECUTABLE "${Python3_EXECUTABLE}")
    endif()
    if(NOT PocoDDSRuntime_CONFIGURATION_PARTICIPANT_CONTRACT_TOOL OR
       NOT EXISTS "${PocoDDSRuntime_CONFIGURATION_PARTICIPANT_CONTRACT_TOOL}")
        message(FATAL_ERROR
            "Installed configuration participant contract tool is unavailable: "
            "${PocoDDSRuntime_CONFIGURATION_PARTICIPANT_CONTRACT_TOOL}")
    endif()

    get_filename_component(declaration "${PDR_PARTICIPANT_DECLARATION}" ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    if(NOT EXISTS "${declaration}")
        message(FATAL_ERROR
            "Configuration participant declaration does not exist: ${declaration}")
    endif()
    if(PDR_PARTICIPANT_REPORT)
        get_filename_component(report "${PDR_PARTICIPANT_REPORT}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}")
    else()
        set(report
            "${CMAKE_CURRENT_BINARY_DIR}/reports/${PDR_PARTICIPANT_NAME}.json")
    endif()
    set(command
        "${PDR_PARTICIPANT_PYTHON_EXECUTABLE}"
        "${PocoDDSRuntime_CONFIGURATION_PARTICIPANT_CONTRACT_TOOL}"
        --declaration "${declaration}"
        --report "${report}")
    foreach(provider IN LISTS PDR_PARTICIPANT_PROVIDER_DECLARATIONS)
        get_filename_component(provider_path "${provider}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${provider_path}")
            message(FATAL_ERROR
                "Provider participant declaration does not exist: ${provider_path}")
        endif()
        list(APPEND command --declaration "${provider_path}")
    endforeach()
    if(PDR_PARTICIPANT_BASELINE)
        get_filename_component(baseline "${PDR_PARTICIPANT_BASELINE}" ABSOLUTE
            BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        if(NOT EXISTS "${baseline}")
            message(FATAL_ERROR
                "Configuration participant baseline does not exist: ${baseline}")
        endif()
        list(APPEND command --baseline "${baseline}")
    endif()

    add_test(NAME "${PDR_PARTICIPANT_NAME}" COMMAND ${command})
    set(labels configuration participant contract dependency conformance isolated)
    list(APPEND labels ${PDR_PARTICIPANT_LABELS})
    list(REMOVE_DUPLICATES labels)
    set_tests_properties("${PDR_PARTICIPANT_NAME}" PROPERTIES
        LABELS "${labels}"
        TIMEOUT 15)
endfunction()
