#!/usr/bin/env python3
"""Persistent canary/wave rollout coordinator for Adapter Catalog nodes."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import process_file_lease as process_lease
import team_contract_adapter_runtime as adapter_runtime
import team_contract_adapter_catalog_control_authorizer as control_authorizer_tool
import team_contract_adapter_catalog_fleet_state_store as fleet_state_store_tool
import team_contract_adapter_catalog_wave_gate as wave_gate_tool
import team_contract_adapter_config_resolver as adapter_config_resolver_tool
import team_contract_adapter_conformance_admission as admission_tool
import team_contract_package as package_tool
import team_contract_registry as registry_tool


PLAN_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetPlan"
EXECUTOR_CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorConfig"
CAPABILITY_REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorCapabilityManifest"
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorResponse"
JOURNAL_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetJournal"
REPORT_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetReport"
STATUS_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetStatus"
REQUIRED_CAPABILITIES = [
    "idempotent-node-deploy", "node-reconcile-status",
    "reverse-order-revert", "wave-rollout",
]
FLEET_STATUSES = {
    "running", "paused", "rolling-back", "rollback-failed", "committed",
    "rolled-back",
}
NODE_STATUSES = {
    "pending", "deploying", "committed", "failed", "rolling-back",
    "rolled-back", "rollback-failed",
}
MAX_NODES = 1024
PATH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
GATE_STATUSES = {"pending", "waiting", "evaluating", "passed", "paused", "failed"}
CONTROL_ACTIONS = {"resume", "abort"}


def validate_executor_config(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "executorId", "kind", "protocolMajor",
        "minimumProtocolMinor", "requiredCapabilities", "executable",
        "executableSha256", "arguments", "artifactPins",
        "environmentVariables", "optionalEnvironmentVariables",
        "timeoutSeconds", "maxResponseBytes",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != EXECUTOR_CONFIG_PRODUCT
            or package_tool.IDENTIFIER.fullmatch(
                str(document.get("executorId", ""))) is None
            or document.get("kind") != "external-command"
            or type(document.get("protocolMajor")) is not int
            or not 1 <= document["protocolMajor"] <= 65535
            or type(document.get("minimumProtocolMinor")) is not int
            or not 0 <= document["minimumProtocolMinor"] <= 65535
            or document.get("requiredCapabilities") != REQUIRED_CAPABILITIES
            or not isinstance(document.get("executable"), str)
            or package_tool.SHA256.fullmatch(
                str(document.get("executableSha256", ""))) is None
            or not isinstance(document.get("arguments"), list)
            or len(document["arguments"]) > 32
            or any(not isinstance(item, str) or not item or "\x00" in item
                   or len(item) > 1024 for item in document["arguments"])
            or type(document.get("timeoutSeconds")) is not int
            or not 1 <= document["timeoutSeconds"] <= 120
            or type(document.get("maxResponseBytes")) is not int
            or not 1024 <= document["maxResponseBytes"] <= 1024 * 1024):
        raise ValueError("Adapter Catalog Fleet Executor config is malformed")
    adapter_runtime.validate_artifact_pins(document["artifactPins"], "fleet executor")
    adapter_runtime.validate_environment_policy(
        document["environmentVariables"],
        optional=document["optionalEnvironmentVariables"],
        label="fleet executor",
    )


def load_executor_config(path_value: str | Path, expected_sha: str) \
        -> tuple[dict[str, Any], Path, str]:
    config, path, digest = adapter_runtime.load_pinned_json(
        path_value, expected_sha, "Adapter Catalog Fleet Executor config",
        validate_executor_config,
    )
    adapter_runtime.revalidate_artifacts(config, "fleet executor")
    return config, path, digest


def validate_plan(document: Any) -> None:
    legacy_fields = {
        "schemaVersion", "product", "rolloutId", "catalogId",
        "candidateCatalogGeneration", "candidateCatalogSha256",
        "executorConfigPath", "executorConfigSha256", "maxParallelNodes",
        "waves",
    }
    version = document.get("schemaVersion") if isinstance(document, dict) else None
    fields = set(legacy_fields)
    if version in {2, 3, 4}:
        fields |= {"gateConfigPath", "gateConfigSha256"}
    if version in {3, 4}:
        fields |= {
            "controlAuthorizerConfigPath", "controlAuthorizerConfigSha256",
        }
    if version == 4:
        fields |= {
            "stateBackendId", "stateBackendConfigSha256",
            "artifactStoreId", "artifactStoreConfigSha256",
        }
    if version in {5, 6, 7}:
        fields = {
            "schemaVersion", "product", "rolloutId", "catalogId",
            "candidateCatalogGeneration", "candidateCatalogSha256",
            "maxParallelNodes", "waves", "adapterConfigResolverId",
            "executorConfigRef", "gateConfigRef",
            "controlAuthorizerConfigRef", "stateBackendConfigRef",
            "artifactStoreConfigRef",
        }
        if version in {6, 7}:
            fields.add("adapterConformancePolicy")
        if version == 7:
            fields.add("adapterConformanceTrustPolicy")
    if (not isinstance(document, dict)
            or version not in {1, 2, 3, 4, 5, 6, 7}
            or set(document) != fields
            or document.get("product") != PLAN_PRODUCT
            or PATH_ID.fullmatch(str(document.get("rolloutId", ""))) is None
            or package_tool.IDENTIFIER.fullmatch(
                str(document.get("catalogId", ""))) is None
            or type(document.get("candidateCatalogGeneration")) is not int
            or document["candidateCatalogGeneration"] < 2
            or package_tool.SHA256.fullmatch(
                str(document.get("candidateCatalogSha256", ""))) is None
            or type(document.get("maxParallelNodes")) is not int
            or not 1 <= document["maxParallelNodes"] <= 16
            or not isinstance(document.get("waves"), list)
            or not 1 <= len(document["waves"]) <= 32):
        raise ValueError("Adapter Catalog Fleet plan is malformed")
    if version <= 4 and (
            not isinstance(document.get("executorConfigPath"), str)
            or not Path(document["executorConfigPath"]).is_absolute()
            or package_tool.SHA256.fullmatch(
                str(document.get("executorConfigSha256", ""))) is None):
        raise ValueError("Adapter Catalog Fleet Executor identity is malformed")
    if version in {2, 3, 4} and (
            not isinstance(document.get("gateConfigPath"), str)
            or not Path(document["gateConfigPath"]).is_absolute()
            or package_tool.SHA256.fullmatch(
                str(document.get("gateConfigSha256", ""))) is None):
        raise ValueError("Adapter Catalog Fleet Wave Gate identity is malformed")
    if version in {3, 4} and (
            not isinstance(document.get("controlAuthorizerConfigPath"), str)
            or not Path(document["controlAuthorizerConfigPath"]).is_absolute()
            or package_tool.SHA256.fullmatch(str(
                document.get("controlAuthorizerConfigSha256", ""))) is None):
        raise ValueError(
            "Adapter Catalog Fleet Control Authorizer identity is malformed"
        )
    if version == 4 and (
            any(package_tool.IDENTIFIER.fullmatch(str(
                document.get(name, ""))) is None
                for name in ("stateBackendId", "artifactStoreId"))
            or any(package_tool.SHA256.fullmatch(str(
                document.get(name, ""))) is None
                for name in (
                    "stateBackendConfigSha256",
                    "artifactStoreConfigSha256",
                ))):
        raise ValueError("Adapter Catalog Fleet State Store identity is malformed")
    if version in {5, 6, 7}:
        resolver_id = str(document.get("adapterConfigResolverId", ""))
        if package_tool.IDENTIFIER.fullmatch(resolver_id) is None:
            raise ValueError(
                "Adapter Catalog Fleet Config Resolver identity is malformed"
            )
        for field, adapter_kind in (
                ("executorConfigRef", "fleet-executor"),
                ("gateConfigRef", "wave-gate"),
                ("controlAuthorizerConfigRef", "control-authorizer"),
                ("stateBackendConfigRef", "registry-leader-backend"),
                ("artifactStoreConfigRef", "artifact-store")):
            adapter_config_resolver_tool.validate_reference(
                document[field], resolver_id=resolver_id,
                adapter_kind=adapter_kind,
            )
        if version in {6, 7}:
            admission_tool.validate_policy(
                document.get("adapterConformancePolicy")
            )
        if version == 7:
            admission_tool.validate_trust_requirement(
                document.get("adapterConformanceTrustPolicy")
            )
    wave_ids: set[str] = set()
    node_ids: set[str] = set()
    total = 0
    for wave_index, wave in enumerate(document["waves"]):
        wave_fields = {"waveId", "mode", "maxFailures", "nodes"}
        if version in {2, 3, 4, 5, 6, 7}:
            wave_fields.add("gatePolicy")
        if (not isinstance(wave, dict) or set(wave) != wave_fields
                or PATH_ID.fullmatch(
                str(wave.get("waveId", ""))) is None
                or wave["waveId"] in wave_ids
                or wave.get("mode") not in {"canary", "wave"}
                or (wave_index == 0) != (wave.get("mode") == "canary")
                or type(wave.get("maxFailures")) is not int
                or not isinstance(wave.get("nodes"), list)
                or not wave["nodes"]
                or not 0 <= wave["maxFailures"] < len(wave["nodes"])
                or (wave_index == 0 and wave["maxFailures"] != 0)):
            raise ValueError("Adapter Catalog Fleet wave is malformed")
        if version in {2, 3, 4, 5, 6, 7}:
            policy = wave.get("gatePolicy")
            if (not isinstance(policy, dict) or set(policy) != {
                    "minimumObservationSeconds", "maxEvaluations",
                    "rejectionAction",
                } or type(policy.get("minimumObservationSeconds")) is not int
                    or not 0 <= policy["minimumObservationSeconds"] <= 86400
                    or type(policy.get("maxEvaluations")) is not int
                    or not 1 <= policy["maxEvaluations"] <= 100
                    or policy.get("rejectionAction") not in {
                        "pause", "rollback",
                    }):
                raise ValueError("Adapter Catalog Fleet Wave Gate policy is malformed")
        wave_ids.add(wave["waveId"])
        for node in wave["nodes"]:
            if (not isinstance(node, dict) or set(node) != {
                    "nodeId", "failureDomain", "expectedActivationGeneration"
                } or PATH_ID.fullmatch(str(node.get("nodeId", ""))) is None
                    or package_tool.IDENTIFIER.fullmatch(
                        str(node.get("failureDomain", ""))) is None
                    or node["nodeId"] in node_ids
                    or package_tool.IDENTIFIER.fullmatch(
                        f"{document['rolloutId']}.{node['nodeId']}") is None
                    or type(node.get("expectedActivationGeneration")) is not int
                    or node["expectedActivationGeneration"] < 1):
                raise ValueError("Adapter Catalog Fleet node is malformed")
            node_ids.add(node["nodeId"])
        if wave["nodes"] != sorted(wave["nodes"], key=lambda item: item["nodeId"]):
            raise ValueError("Adapter Catalog Fleet nodes are not sorted")
        total += len(wave["nodes"])
    if total > MAX_NODES:
        raise ValueError("Adapter Catalog Fleet plan exceeds node capacity")


def load_plan(path_value: str | Path, expected_sha: str) \
        -> tuple[dict[str, Any], Path, str]:
    return adapter_runtime.load_pinned_json(
        path_value, expected_sha, "Adapter Catalog Fleet plan", validate_plan
    )


def invoke_executor(config: dict[str, Any], request: dict[str, Any]) \
        -> dict[str, Any]:
    adapter_runtime.revalidate_artifacts(config, "fleet executor")
    environment = adapter_runtime.isolated_environment(
        config["environmentVariables"],
        optional=config["optionalEnvironmentVariables"],
        require_required=True, label="fleet executor",
    )
    return adapter_runtime.invoke_json(
        [str(Path(config["executable"]).resolve()), *config["arguments"]],
        request, environment=environment,
        timeout_seconds=config["timeoutSeconds"],
        max_response_bytes=config["maxResponseBytes"],
        label="Adapter Catalog Fleet Executor", expose_stderr=False,
    )


def negotiate(config: dict[str, Any]) -> str:
    request = {
        "schemaVersion": 1, "product": CAPABILITY_REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "executorId": config["executorId"],
    }
    response = invoke_executor(config, request)
    fields = {
        "schemaVersion", "product", "requestId", "executorId",
        "implementationId", "protocolMajor", "protocolMinor", "capabilities",
    }
    if (not isinstance(response, dict) or set(response) != fields
            or response.get("schemaVersion") != 1
            or response.get("product") != CAPABILITY_MANIFEST_PRODUCT
            or response.get("requestId") != request["requestId"]
            or response.get("executorId") != config["executorId"]
            or package_tool.IDENTIFIER.fullmatch(
                str(response.get("implementationId", ""))) is None
            or type(response.get("protocolMajor")) is not int
            or type(response.get("protocolMinor")) is not int
            or not isinstance(response.get("capabilities"), list)
            or response["capabilities"] != sorted(set(response["capabilities"]))
            or any(adapter_runtime.CAPABILITY_ID.fullmatch(str(item)) is None
                   for item in response["capabilities"])):
        raise ValueError("Fleet Executor capability manifest is malformed")
    adapter_runtime.enforce_capability_policy(config, response, "fleet executor")
    return adapter_runtime.capability_digest(response, "executorId")


def validate_executor_response(response: Any, request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "executorId", "rolloutId",
        "nodeId", "operation", "accepted", "state",
        "currentActivationGeneration", "reconcileReportSha256",
        "diagnosticCode",
    }
    if (not isinstance(response, dict) or set(response) != fields
            or response.get("schemaVersion") != 1
            or response.get("product") != RESPONSE_PRODUCT
            or any(response.get(name) != request[name] for name in (
                "requestId", "executorId", "rolloutId", "nodeId", "operation"))
            or type(response.get("accepted")) is not bool
            or response.get("state") not in {
                "committed", "rolled-back", "failed", "unknown"
            }
            or type(response.get("currentActivationGeneration")) is not int
            or response["currentActivationGeneration"] < 1
            or (response.get("reconcileReportSha256") is not None
                and package_tool.SHA256.fullmatch(
                    str(response["reconcileReportSha256"])) is None)
            or (response.get("diagnosticCode") is not None
                and package_tool.IDENTIFIER.fullmatch(
                    str(response["diagnosticCode"])) is None)):
        raise ValueError("Fleet Executor response is malformed or mismatched")


def node_request(plan: dict[str, Any], config: dict[str, Any],
                 node: dict[str, Any], operation: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "executorId": config["executorId"],
        "rolloutId": plan["rolloutId"], "nodeId": node["nodeId"],
        "operation": operation, "catalogId": plan["catalogId"],
        "candidateCatalogGeneration": plan["candidateCatalogGeneration"],
        "candidateCatalogSha256": plan["candidateCatalogSha256"],
        "expectedActivationGeneration": node["expectedActivationGeneration"],
    }


def execute_node(plan: dict[str, Any], config: dict[str, Any],
                 node: dict[str, Any], operation: str) -> dict[str, Any]:
    request = node_request(plan, config, node, operation)
    try:
        response = invoke_executor(config, request)
        validate_executor_response(response, request)
        return response
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError):
        if operation != "status":
            status_request = node_request(plan, config, node, "status")
            try:
                status = invoke_executor(config, status_request)
                validate_executor_response(status, status_request)
                succeeded = (
                    operation == "deploy" and status["state"] == "committed"
                ) or (
                    operation == "revert" and status["state"] == "rolled-back"
                )
                if succeeded:
                    return {
                        **status, "requestId": request["requestId"],
                        "operation": operation, "accepted": True,
                        "diagnosticCode": None,
                    }
                if status["state"] in {"committed", "rolled-back", "failed"}:
                    return {
                        **status, "requestId": request["requestId"],
                        "operation": operation, "accepted": False,
                        "state": "failed",
                        "diagnosticCode": f"node-{operation}-terminal-mismatch",
                    }
                return {
                    **status, "requestId": request["requestId"],
                    "operation": operation, "accepted": False,
                    "state": "unknown",
                    "diagnosticCode": "executor-result-ambiguous",
                }
            except (OSError, UnicodeError, ValueError, RuntimeError,
                    json.JSONDecodeError):
                pass
        return {
            "schemaVersion": 1, "product": RESPONSE_PRODUCT,
            "requestId": request["requestId"],
            "executorId": request["executorId"],
            "rolloutId": request["rolloutId"], "nodeId": request["nodeId"],
            "operation": operation, "accepted": False, "state": "unknown",
            "currentActivationGeneration": node["expectedActivationGeneration"],
            "reconcileReportSha256": None,
            "diagnosticCode": "executor-result-ambiguous",
        }


def self_digest(document: dict[str, Any]) -> str:
    return package_tool.sha256_bytes(package_tool.json_bytes({
        key: value for key, value in document.items() if key != "journalSha256"
    }))


def validate_journal(journal: Any, plan: dict[str, Any]) -> None:
    base_fields = {
        "schemaVersion", "product", "rolloutId", "planSha256",
        "catalogId", "candidateCatalogGeneration",
        "candidateCatalogSha256", "status", "currentWave", "failedWave",
        "nodes", "createdAt", "updatedAt", "journalSha256",
    }
    fields = set(base_fields)
    if plan["schemaVersion"] <= 4:
        fields.add("executorConfigSha256")
    if plan["schemaVersion"] >= 2:
        fields |= {
            "gates", "controlGeneration", "controls",
        }
        if plan["schemaVersion"] <= 4:
            fields.add("gateConfigSha256")
    if plan["schemaVersion"] >= 3:
        fields.add("authorizationAttempts")
        if plan["schemaVersion"] <= 4:
            fields.add("controlAuthorizerConfigSha256")
    if plan["schemaVersion"] == 4:
        fields |= {
            "stateBackendConfigSha256", "artifactStoreConfigSha256",
            "stateVersion", "previousJournalSha256", "lastCoordinatorId",
        }
    if plan["schemaVersion"] in {5, 6, 7}:
        fields |= {
            "adapterConfigResolverId", "executorConfigRef", "gateConfigRef",
            "controlAuthorizerConfigRef", "stateBackendConfigRef",
            "artifactStoreConfigRef", "stateVersion",
            "previousJournalSha256", "lastCoordinatorId",
        }
        if plan["schemaVersion"] in {6, 7}:
            fields |= {"adapterConformancePolicy", "admissions"}
        if plan["schemaVersion"] == 7:
            fields.add("adapterConformanceTrustPolicy")
    if (not isinstance(journal, dict) or set(journal) != fields
            or journal.get("schemaVersion") != plan["schemaVersion"]
            or journal.get("product") != JOURNAL_PRODUCT
            or journal.get("rolloutId") != plan["rolloutId"]
            or journal.get("catalogId") != plan["catalogId"]
            or journal.get("candidateCatalogGeneration")
                != plan["candidateCatalogGeneration"]
            or journal.get("candidateCatalogSha256")
                != plan["candidateCatalogSha256"]
            or journal.get("status") not in FLEET_STATUSES
            or (plan["schemaVersion"] == 1 and journal.get("status") == "paused")
            or type(journal.get("currentWave")) is not int
            or not 0 <= journal["currentWave"] <= len(plan["waves"])
            or (journal.get("failedWave") is not None
                and (type(journal["failedWave"]) is not int
                     or not 0 <= journal["failedWave"] < len(plan["waves"])))
            or any(package_tool.SHA256.fullmatch(str(
                journal.get(name, ""))) is None
                for name in ("planSha256", "journalSha256"))
            or not isinstance(journal.get("nodes"), list)
            or len(journal["nodes"]) != sum(
                len(wave["nodes"]) for wave in plan["waves"])
            or journal["journalSha256"] != self_digest(journal)):
        raise ValueError("Adapter Catalog Fleet journal is malformed")
    if plan["schemaVersion"] <= 4 and (
            journal.get("executorConfigSha256")
                != plan["executorConfigSha256"]
            or package_tool.SHA256.fullmatch(str(
                journal.get("executorConfigSha256", ""))) is None):
        raise ValueError("Adapter Catalog Fleet Executor journal is malformed")
    if plan["schemaVersion"] >= 2 and (
            type(journal.get("controlGeneration")) is not int
            or not 0 <= journal["controlGeneration"] <= 100
            or not isinstance(journal.get("gates"), list)
            or len(journal["gates"]) != len(plan["waves"])
            or not isinstance(journal.get("controls"), list)
            or len(journal["controls"]) != journal["controlGeneration"]):
        raise ValueError("Adapter Catalog Fleet Wave Gate journal is malformed")
    if 2 <= plan["schemaVersion"] <= 4 and (
            journal.get("gateConfigSha256") != plan["gateConfigSha256"]):
        raise ValueError("Adapter Catalog Fleet Wave Gate identity changed")
    if plan["schemaVersion"] >= 3 and (
            not isinstance(journal.get("authorizationAttempts"), list)
            or len(journal["authorizationAttempts"]) > 200):
        raise ValueError(
            "Adapter Catalog Fleet Control Authorizer journal is malformed"
        )
    if 3 <= plan["schemaVersion"] <= 4 and (
            journal.get("controlAuthorizerConfigSha256")
                != plan["controlAuthorizerConfigSha256"]):
        raise ValueError(
            "Adapter Catalog Fleet Control Authorizer identity changed"
        )
    if plan["schemaVersion"] == 4 and (
            journal.get("stateBackendConfigSha256")
                != plan["stateBackendConfigSha256"]
            or journal.get("artifactStoreConfigSha256")
                != plan["artifactStoreConfigSha256"]
            or type(journal.get("stateVersion")) is not int
            or journal["stateVersion"] < 1):
        raise ValueError("Adapter Catalog Fleet remote journal is malformed")
    if plan["schemaVersion"] in {5, 6, 7} and (
            journal.get("adapterConfigResolverId")
                != plan["adapterConfigResolverId"]
            or any(journal.get(field) != plan[field] for field in (
                "executorConfigRef", "gateConfigRef",
                "controlAuthorizerConfigRef", "stateBackendConfigRef",
                "artifactStoreConfigRef",
            ))):
        raise ValueError("Adapter Catalog Fleet portable identity changed")
    if plan["schemaVersion"] in {6, 7}:
        if (journal.get("adapterConformancePolicy")
                != plan["adapterConformancePolicy"]
                or not isinstance(journal.get("admissions"), list)
                or not 1 <= len(journal["admissions"]) <= 200):
            raise ValueError(
                "Adapter Catalog Fleet conformance admission journal is malformed"
            )
        for admission in journal["admissions"]:
            admission_tool.validate_summary(admission)
            if admission["policyId"] != \
                    plan["adapterConformancePolicy"]["policyId"]:
                raise ValueError(
                    "Adapter Catalog Fleet conformance policy identity changed"
                )
        if plan["schemaVersion"] == 7:
            if journal.get("adapterConformanceTrustPolicy") != \
                    plan["adapterConformanceTrustPolicy"]:
                raise ValueError(
                    "Adapter Catalog Fleet trust policy identity changed"
                )
            for admission in journal["admissions"]:
                if (admission.get("trustPolicyId")
                        != plan["adapterConformanceTrustPolicy"]["policyId"]
                        or admission.get("trustPolicyGeneration", 0)
                        < plan["adapterConformanceTrustPolicy"][
                            "minimumGeneration"]):
                    raise ValueError(
                        "Adapter Catalog Fleet signed admission is malformed"
                    )
    if plan["schemaVersion"] >= 4 and (
            type(journal.get("stateVersion")) is not int
            or journal["stateVersion"] < 1
            or (journal["stateVersion"] == 1
                and journal.get("previousJournalSha256") is not None)
            or (journal["stateVersion"] > 1
                and package_tool.SHA256.fullmatch(str(
                    journal.get("previousJournalSha256", ""))) is None)
            or package_tool.IDENTIFIER.fullmatch(str(
                journal.get("lastCoordinatorId", ""))) is None):
        raise ValueError("Adapter Catalog Fleet remote journal is malformed")
    expected = []
    for wave_index, wave in enumerate(plan["waves"]):
        for node in wave["nodes"]:
            expected.append((node["nodeId"], wave_index))
    observed = []
    for node in journal["nodes"]:
        if (not isinstance(node, dict) or set(node) != {
                "nodeId", "waveIndex", "status", "attempts", "errorCode",
                "reconcileReportSha256", "currentActivationGeneration",
                "updatedAt",
            } or node.get("status") not in NODE_STATUSES
                or type(node.get("attempts")) is not int
                or not 0 <= node["attempts"] <= 100
                or type(node.get("currentActivationGeneration")) is not int
                or node["currentActivationGeneration"] < 1
                or (node.get("errorCode") is not None
                    and package_tool.IDENTIFIER.fullmatch(
                        str(node["errorCode"])) is None)
                or (node.get("reconcileReportSha256") is not None
                    and package_tool.SHA256.fullmatch(
                        str(node["reconcileReportSha256"])) is None)):
            raise ValueError("Adapter Catalog Fleet node journal is malformed")
        package_tool.parse_time(node.get("updatedAt"), "Fleet node updatedAt")
        observed.append((node["nodeId"], node["waveIndex"]))
    if observed != expected:
        raise ValueError("Adapter Catalog Fleet journal node identity changed")
    created = package_tool.parse_time(journal.get("createdAt"), "Fleet createdAt")
    updated = package_tool.parse_time(journal.get("updatedAt"), "Fleet updatedAt")
    if updated < created:
        raise ValueError("Adapter Catalog Fleet journal time moved backwards")
    if plan["schemaVersion"] >= 2:
        observed_gates = []
        for gate in journal["gates"]:
            if (not isinstance(gate, dict) or set(gate) != {
                    "waveId", "waveIndex", "status", "attempts",
                    "observationStartedAt", "evidenceSha256",
                    "diagnosticCode", "updatedAt",
                } or gate.get("status") not in GATE_STATUSES
                    or type(gate.get("waveIndex")) is not int
                    or type(gate.get("attempts")) is not int
                    or not 0 <= gate["attempts"] <= 100
                    or (gate.get("observationStartedAt") is not None
                        and not isinstance(gate["observationStartedAt"], str))
                    or (gate.get("evidenceSha256") is not None
                        and package_tool.SHA256.fullmatch(
                            str(gate["evidenceSha256"])) is None)
                    or (gate.get("diagnosticCode") is not None
                        and package_tool.IDENTIFIER.fullmatch(
                            str(gate["diagnosticCode"])) is None)):
                raise ValueError("Adapter Catalog Fleet gate record is malformed")
            if gate["observationStartedAt"] is not None:
                package_tool.parse_time(
                    gate["observationStartedAt"], "Fleet gate observation start"
                )
            package_tool.parse_time(gate["updatedAt"], "Fleet gate updatedAt")
            observed_gates.append((gate["waveId"], gate["waveIndex"]))
        expected_gates = [
            (wave["waveId"], index) for index, wave in enumerate(plan["waves"])
        ]
        if observed_gates != expected_gates:
            raise ValueError("Adapter Catalog Fleet gate identity changed")
        seen_controls: set[str] = set()
        for index, control in enumerate(journal["controls"], start=1):
            control_fields = {
                "generation", "operationId", "action", "actor", "reason",
                "waveIndex", "at",
            }
            if plan["schemaVersion"] >= 3:
                control_fields |= {
                    "authorizationId", "authorizationEvidenceSha256",
                }
            if (not isinstance(control, dict) or set(control) != control_fields
                    or control.get("generation") != index
                    or package_tool.IDENTIFIER.fullmatch(
                        str(control.get("operationId", ""))) is None
                    or control["operationId"] in seen_controls
                    or control.get("action") not in CONTROL_ACTIONS
                    or package_tool.IDENTIFIER.fullmatch(
                        str(control.get("actor", ""))) is None
                    or not isinstance(control.get("reason"), str)
                    or not 1 <= len(control["reason"]) <= 512
                    or "\r" in control["reason"] or "\n" in control["reason"]
                    or type(control.get("waveIndex")) is not int
                    or not 0 <= control["waveIndex"] < len(plan["waves"])
                    or (plan["schemaVersion"] >= 3 and (
                        package_tool.IDENTIFIER.fullmatch(str(
                            control.get("authorizationId", ""))) is None
                        or package_tool.SHA256.fullmatch(str(
                            control.get("authorizationEvidenceSha256", "")))
                            is None))):
                raise ValueError("Adapter Catalog Fleet control record is malformed")
            package_tool.parse_time(control.get("at"), "Fleet control time")
            seen_controls.add(control["operationId"])
        if plan["schemaVersion"] >= 3:
            attempts: dict[str, dict[str, Any]] = {}
            allowed = 0
            for authorization in journal["authorizationAttempts"]:
                if (not isinstance(authorization, dict) or set(authorization) != {
                        "authorizationId", "operationId", "action",
                        "claimedActor", "reasonSha256", "decision",
                        "principalId", "evidenceSha256", "diagnosticCode",
                        "controlGeneration", "waveIndex", "at",
                    } or package_tool.IDENTIFIER.fullmatch(str(
                        authorization.get("authorizationId", ""))) is None
                        or package_tool.IDENTIFIER.fullmatch(str(
                            authorization.get("operationId", ""))) is None
                        or authorization["operationId"] in attempts
                        or authorization.get("action") not in CONTROL_ACTIONS
                        or package_tool.IDENTIFIER.fullmatch(str(
                            authorization.get("claimedActor", ""))) is None
                        or package_tool.SHA256.fullmatch(str(
                            authorization.get("reasonSha256", ""))) is None
                        or authorization.get("decision") not in {"allow", "deny"}
                        or (authorization.get("principalId") is not None
                            and package_tool.IDENTIFIER.fullmatch(str(
                                authorization["principalId"])) is None)
                        or package_tool.SHA256.fullmatch(str(
                            authorization.get("evidenceSha256", ""))) is None
                        or (authorization.get("diagnosticCode") is not None
                            and package_tool.IDENTIFIER.fullmatch(str(
                                authorization["diagnosticCode"])) is None)
                        or type(authorization.get("controlGeneration")) is not int
                        or not 0 <= authorization["controlGeneration"] <= 100
                        or type(authorization.get("waveIndex")) is not int
                        or not 0 <= authorization["waveIndex"] < len(plan["waves"])
                        or (authorization["decision"] == "allow" and (
                            authorization["principalId"]
                                != authorization["claimedActor"]
                            or authorization["diagnosticCode"] is not None))
                        or (authorization["decision"] == "deny"
                            and authorization["diagnosticCode"] is None)):
                    raise ValueError(
                        "Adapter Catalog Fleet authorization record is malformed"
                    )
                package_tool.parse_time(
                    authorization.get("at"), "Fleet authorization time"
                )
                attempts[authorization["operationId"]] = authorization
                allowed += authorization["decision"] == "allow"
            if allowed != journal["controlGeneration"]:
                raise ValueError(
                    "Fleet allowed authorizations do not match controls"
                )
            for control in journal["controls"]:
                authorization = attempts.get(control["operationId"])
                if (authorization is None
                        or authorization["decision"] != "allow"
                        or control["authorizationId"]
                            != authorization["authorizationId"]
                        or control["authorizationEvidenceSha256"]
                            != authorization["evidenceSha256"]
                        or control["actor"] != authorization["principalId"]
                        or control["action"] != authorization["action"]
                        or control["waveIndex"] != authorization["waveIndex"]
                        or control["generation"]
                            != authorization["controlGeneration"] + 1):
                    raise ValueError(
                        "Fleet control authorization linkage is malformed"
                    )
    statuses = [node["status"] for node in journal["nodes"]]
    if journal["status"] == "committed" and (
            journal["currentWave"] != len(plan["waves"])
            or journal["failedWave"] is not None
            or any(status in {"pending", "deploying", "rolling-back",
                              "rolled-back", "rollback-failed"}
                   for status in statuses)):
        raise ValueError("Adapter Catalog Fleet committed state is inconsistent")
    if journal["status"] == "running" and (
            journal["failedWave"] is not None
            or any(status in {"rolling-back", "rolled-back", "rollback-failed"}
                   for status in statuses)):
        raise ValueError("Adapter Catalog Fleet running state is inconsistent")
    if journal["status"] in {"rolling-back", "rollback-failed", "rolled-back"} \
            and journal["failedWave"] is None:
        raise ValueError("Adapter Catalog Fleet rollback has no failed wave")
    if journal["status"] == "rolled-back" and any(
            status in {"committed", "rolling-back", "rollback-failed"}
            for status in statuses):
        raise ValueError("Adapter Catalog Fleet rolled-back state is inconsistent")
    if plan["schemaVersion"] >= 2:
        gate_statuses = [gate["status"] for gate in journal["gates"]]
        if journal["status"] == "committed" and any(
                status != "passed" for status in gate_statuses):
            raise ValueError("Adapter Catalog Fleet committed gates are inconsistent")
        if journal["status"] == "paused" and (
                journal["failedWave"] is not None
                or journal["currentWave"] >= len(plan["waves"])
                or journal["gates"][journal["currentWave"]]["status"]
                    not in {"waiting", "paused"}):
            raise ValueError("Adapter Catalog Fleet paused state is inconsistent")


def state_root(value: str | Path, create: bool = False) -> Path:
    supplied = Path(value)
    linklike = lambda path: path.is_symlink() or bool(
        getattr(path, "is_junction", lambda: False)()
    )
    if linklike(supplied):
        raise ValueError("Adapter Catalog Fleet state root must not be a link")
    root = supplied.resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir() or linklike(root):
        raise FileNotFoundError("Adapter Catalog Fleet state root is unavailable")
    return root


def journal_path(root: Path, rollout_id: str) -> Path:
    if PATH_ID.fullmatch(rollout_id) is None:
        raise ValueError("Fleet rollout ID is malformed")
    directory = root / "rollouts" / rollout_id
    for member in (root / "rollouts", directory):
        if member.is_symlink() or bool(
                getattr(member, "is_junction", lambda: False)()):
            raise ValueError("Fleet journal path must not contain a link")
    return directory / "journal.json"


JournalTarget = Path | fleet_state_store_tool.RemoteFleetStateStore


def write_journal(path: JournalTarget, journal: dict[str, Any]) -> None:
    if isinstance(path, fleet_state_store_tool.RemoteFleetStateStore):
        path.write(journal)
        return
    if path.parent.is_symlink() or bool(
            getattr(path.parent, "is_junction", lambda: False)()):
        raise ValueError("Fleet journal directory must not be a link")
    journal["updatedAt"] = registry_tool.utc_time(None)
    journal["journalSha256"] = self_digest(journal)
    package_tool.write_json(path, journal)


def load_journal(path: JournalTarget, plan: dict[str, Any]) -> dict[str, Any]:
    if isinstance(path, fleet_state_store_tool.RemoteFleetStateStore):
        document = path.read()
        if document is None:
            raise FileNotFoundError(
                "Adapter Catalog Fleet journal is unavailable"
            )
        validate_journal(document, plan)
        return document
    if (path.is_symlink()
            or bool(getattr(path, "is_junction", lambda: False)())
            or not path.is_file()):
        raise FileNotFoundError("Adapter Catalog Fleet journal is unavailable")
    document = json.loads(path.read_bytes())
    validate_journal(document, plan)
    return document


class FleetLease(process_lease.ProcessFileLease):
    def __init__(self, root: Path, rollout_id: str) -> None:
        super().__init__(
            root / ".adapter-catalog-fleet.lock",
            root / ".adapter-catalog-fleet.epoch.json",
            "team-contract-adapter-catalog-fleet",
            {"rolloutId": rollout_id},
        )

    def acquire(self) -> "FleetLease":
        try:
            super().acquire()
            return self
        except process_lease.LeaseBusyError as error:
            raise ValueError("another Adapter Catalog Fleet rollout is active") from error


def node_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        node["nodeId"]: node
        for wave in plan["waves"] for node in wave["nodes"]
    }


def journal_nodes(journal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["nodeId"]: node for node in journal["nodes"]}


def rollback_committed(plan: dict[str, Any], config: dict[str, Any],
                       path: JournalTarget, journal: dict[str, Any]) -> None:
    journal["status"] = "rolling-back"
    write_journal(path, journal)
    definitions = node_map(plan)
    records = journal_nodes(journal)
    ordered = [
        node for wave in reversed(plan["waves"])
        for node in reversed(wave["nodes"])
    ]
    for definition in ordered:
        record = records[definition["nodeId"]]
        if record["status"] == "rolled-back":
            continue
        if record["status"] not in {"committed", "rolling-back",
                                    "rollback-failed"}:
            continue
        record["status"] = "rolling-back"
        record["attempts"] += 1
        record["updatedAt"] = registry_tool.utc_time(None)
        write_journal(path, journal)
        response = execute_node(plan, config, definition, "revert")
        record["currentActivationGeneration"] = \
            response["currentActivationGeneration"]
        record["reconcileReportSha256"] = response["reconcileReportSha256"]
        record["updatedAt"] = registry_tool.utc_time(None)
        if response["accepted"] and response["state"] == "rolled-back":
            record["status"] = "rolled-back"
            record["errorCode"] = None
            write_journal(path, journal)
            continue
        if response["state"] == "unknown":
            record["status"] = "rolling-back"
            record["errorCode"] = (
                response["diagnosticCode"] or "node-revert-ambiguous"
            )
            journal["status"] = "rolling-back"
            write_journal(path, journal)
            return
        record["status"] = "rollback-failed"
        record["errorCode"] = response["diagnosticCode"] or "node-revert-failed"
        journal["status"] = "rollback-failed"
        write_journal(path, journal)
        return
    journal["status"] = "rolled-back"
    write_journal(path, journal)


def deploy_batch(plan: dict[str, Any], config: dict[str, Any],
                 definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=len(definitions)) as executor:
        futures = [
            executor.submit(execute_node, plan, config, node, "deploy")
            for node in definitions
        ]
        return [future.result() for future in futures]


def wave_node_counts(wave: dict[str, Any],
                     records: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {
        status: sum(records[node["nodeId"]]["status"] == status
                    for node in wave["nodes"])
        for status in ("pending", "committed", "failed", "rolled-back")
    }


def observation_elapsed(record: dict[str, Any], policy: dict[str, Any]) -> bool:
    if record["observationStartedAt"] is None:
        return policy["minimumObservationSeconds"] == 0
    started = package_tool.parse_time(
        record["observationStartedAt"], "Fleet gate observation start"
    )
    now = package_tool.parse_time(
        registry_tool.utc_time(None), "Fleet gate current time"
    )
    return (now - started).total_seconds() >= policy["minimumObservationSeconds"]


def fail_wave_gate(plan: dict[str, Any], config: dict[str, Any], path: JournalTarget,
                   journal: dict[str, Any], wave_index: int,
                   diagnostic: str) -> None:
    record = journal["gates"][wave_index]
    record["status"] = "failed"
    record["diagnosticCode"] = diagnostic
    record["updatedAt"] = registry_tool.utc_time(None)
    journal["failedWave"] = wave_index
    journal["status"] = "rolling-back"
    write_journal(path, journal)
    rollback_committed(plan, config, path, journal)


def drive_wave_gate(plan: dict[str, Any], config: dict[str, Any],
                    gate_config: dict[str, Any], path: JournalTarget,
                    journal: dict[str, Any], wave_index: int,
                    records: dict[str, dict[str, Any]]) -> bool:
    wave = plan["waves"][wave_index]
    policy = wave["gatePolicy"]
    record = journal["gates"][wave_index]
    if record["status"] == "passed":
        return True
    if record["status"] == "paused":
        journal["status"] = "paused"
        write_journal(path, journal)
        return False
    if record["observationStartedAt"] is None:
        record["observationStartedAt"] = registry_tool.utc_time(None)
        record["updatedAt"] = record["observationStartedAt"]
        write_journal(path, journal)
    if not observation_elapsed(record, policy):
        record["status"] = "waiting"
        record["diagnosticCode"] = "observation-window-pending"
        record["updatedAt"] = registry_tool.utc_time(None)
        journal["status"] = "paused"
        write_journal(path, journal)
        return False
    if record["status"] != "evaluating":
        if record["attempts"] >= policy["maxEvaluations"]:
            fail_wave_gate(
                plan, config, path, journal, wave_index,
                "wave-gate-evaluation-budget-exhausted",
            )
            return False
        record["status"] = "evaluating"
        record["attempts"] += 1
        record["diagnosticCode"] = None
        record["updatedAt"] = registry_tool.utc_time(None)
        journal["status"] = "running"
        write_journal(path, journal)
    response = wave_gate_tool.evaluate(
        gate_config, rollout_id=plan["rolloutId"], wave_id=wave["waveId"],
        wave_index=wave_index, catalog_id=plan["catalogId"],
        candidate_generation=plan["candidateCatalogGeneration"],
        candidate_sha=plan["candidateCatalogSha256"],
        attempt=record["attempts"],
        observation_started_at=record["observationStartedAt"],
        node_counts=wave_node_counts(wave, records),
    )
    record["evidenceSha256"] = response["evidenceSha256"]
    record["diagnosticCode"] = response["diagnosticCode"]
    record["updatedAt"] = registry_tool.utc_time(None)
    if response["accepted"] and response["decision"] == "pass":
        record["status"] = "passed"
        record["diagnosticCode"] = None
        write_journal(path, journal)
        return True
    if (response["decision"] == "pause"
            and policy["rejectionAction"] == "pause"
            and record["attempts"] < policy["maxEvaluations"]):
        record["status"] = "paused"
        journal["status"] = "paused"
        write_journal(path, journal)
        return False
    fail_wave_gate(
        plan, config, path, journal, wave_index,
        response["diagnosticCode"] or "wave-gate-rejected",
    )
    return False


def drive(plan: dict[str, Any], config: dict[str, Any], path: JournalTarget,
          journal: dict[str, Any],
          gate_config: dict[str, Any] | None = None) -> None:
    if journal["status"] in {"rolling-back", "rollback-failed"}:
        rollback_committed(plan, config, path, journal)
        return
    if journal["status"] in {"committed", "rolled-back"}:
        return
    if journal["status"] == "paused":
        gate = journal["gates"][journal["currentWave"]]
        if gate["status"] == "paused":
            return
        journal["status"] = "running"
        write_journal(path, journal)
    records = journal_nodes(journal)
    for wave_index in range(journal["currentWave"], len(plan["waves"])):
        wave = plan["waves"][wave_index]
        journal["currentWave"] = wave_index
        write_journal(path, journal)
        remaining = [
            node for node in wave["nodes"]
            if records[node["nodeId"]]["status"] in {"pending", "deploying"}
        ]
        failures = sum(
            records[node["nodeId"]]["status"] == "failed"
            for node in wave["nodes"]
        )
        if failures > wave["maxFailures"]:
            journal["failedWave"] = wave_index
            journal["status"] = "rolling-back"
            write_journal(path, journal)
            rollback_committed(plan, config, path, journal)
            return
        while remaining:
            batch = remaining[:plan["maxParallelNodes"]]
            for definition in batch:
                record = records[definition["nodeId"]]
                record["status"] = "deploying"
                record["attempts"] += 1
                record["updatedAt"] = registry_tool.utc_time(None)
            write_journal(path, journal)
            responses = deploy_batch(plan, config, batch)
            ambiguous = False
            for definition, response in zip(batch, responses):
                record = records[definition["nodeId"]]
                record["currentActivationGeneration"] = \
                    response["currentActivationGeneration"]
                record["reconcileReportSha256"] = \
                    response["reconcileReportSha256"]
                record["updatedAt"] = registry_tool.utc_time(None)
                if response["accepted"] and response["state"] == "committed":
                    record["status"] = "committed"
                    record["errorCode"] = None
                elif response["state"] == "unknown":
                    record["status"] = "deploying"
                    record["errorCode"] = (
                        response["diagnosticCode"] or "node-deploy-ambiguous"
                    )
                    ambiguous = True
                else:
                    record["status"] = "failed"
                    record["errorCode"] = (
                        response["diagnosticCode"] or "node-deploy-failed"
                    )
            write_journal(path, journal)
            if ambiguous:
                return
            failures = sum(
                records[node["nodeId"]]["status"] == "failed"
                for node in wave["nodes"]
            )
            if failures > wave["maxFailures"]:
                journal["failedWave"] = wave_index
                journal["status"] = "rolling-back"
                write_journal(path, journal)
                rollback_committed(plan, config, path, journal)
                return
            remaining = [
                node for node in wave["nodes"]
                if records[node["nodeId"]]["status"] in {"pending", "deploying"}
            ]
        if plan["schemaVersion"] >= 2:
            if gate_config is None:
                raise ValueError("Fleet Wave Gate config is unavailable")
            if not drive_wave_gate(
                    plan, config, gate_config, path, journal, wave_index,
                    records):
                return
            if journal["status"] in {"rolling-back", "rolled-back",
                                     "rollback-failed"}:
                return
        journal["currentWave"] = wave_index + 1
        write_journal(path, journal)
    journal["status"] = "committed"
    write_journal(path, journal)


def report_for(journal: dict[str, Any], capability_sha: str,
               gate_capability_sha: str | None = None,
               authorizer_capability_sha: str | None = None,
               state_store: fleet_state_store_tool.RemoteFleetStateStore | None = None,
               resolver_capability_sha: str | None = None) \
        -> dict[str, Any]:
    counts = {
        status: sum(node["status"] == status for node in journal["nodes"])
        for status in NODE_STATUSES
    }
    report = {
        "schemaVersion": journal["schemaVersion"], "product": REPORT_PRODUCT,
        "passed": journal["status"] == "committed",
        "rolloutId": journal["rolloutId"], "status": journal["status"],
        "catalogId": journal["catalogId"],
        "candidateCatalogGeneration": journal["candidateCatalogGeneration"],
        "candidateCatalogSha256": journal["candidateCatalogSha256"],
        "waveCount": journal["currentWave"],
        "failedWave": journal["failedWave"],
        "committedNodes": counts["committed"],
        "failedNodes": counts["failed"],
        "pendingNodes": counts["pending"],
        "rolledBackNodes": counts["rolled-back"],
        "rollbackFailedNodes": counts["rollback-failed"],
        "journalSha256": journal["journalSha256"],
        "reportedAt": registry_tool.utc_time(None),
    }
    if journal["schemaVersion"] == 1:
        report["capabilityManifestSha256"] = capability_sha
    else:
        gate_counts = {
            status: sum(gate["status"] == status for gate in journal["gates"])
            for status in GATE_STATUSES
        }
        report.update({
            "nodeExecutorCapabilityManifestSha256": capability_sha,
            "waveGateCapabilityManifestSha256": gate_capability_sha,
            "gateCounts": gate_counts,
            "controlGeneration": journal["controlGeneration"],
        })
        if journal["schemaVersion"] >= 3:
            report.update({
                "controlAuthorizerCapabilityManifestSha256":
                    authorizer_capability_sha,
                "authorizationCounts": {
                    decision: sum(
                        item["decision"] == decision
                        for item in journal["authorizationAttempts"]
                    ) for decision in ("allow", "deny")
                },
            })
        if journal["schemaVersion"] >= 4:
            if state_store is None:
                raise ValueError("Fleet remote State Store is unavailable")
            report.update({
                "stateBackendCapabilityManifestSha256":
                    state_store.backend_capability_manifest_sha256,
                "artifactStoreCapabilityManifestSha256":
                    state_store.artifact_store_capability_manifest_sha256,
                "stateVersion": journal["stateVersion"],
                "lastCoordinatorId": journal["lastCoordinatorId"],
            })
        if journal["schemaVersion"] in {5, 6, 7}:
            if resolver_capability_sha is None:
                raise ValueError(
                    "Fleet Adapter Config Resolver capability is unavailable"
                )
            report["adapterConfigResolverCapabilityManifestSha256"] = \
                resolver_capability_sha
        if journal["schemaVersion"] in {6, 7}:
            report.update({
                "adapterConformanceAdmissionId":
                    journal["admissions"][-1]["admissionId"],
                "adapterConformanceAdmissionCount":
                    len(journal["admissions"]),
            })
            if journal["schemaVersion"] == 7:
                latest = journal["admissions"][-1]
                report.update({
                    "adapterConformanceTrustPolicyId":
                        latest["trustPolicyId"],
                    "adapterConformanceTrustPolicyGeneration":
                        latest["trustPolicyGeneration"],
                    "adapterConformanceTrustPolicySha256":
                        latest["trustPolicySha256"],
                })
    return report


def create_journal(plan: dict[str, Any], plan_sha: str,
                   config_sha: str | None,
                   admission: dict[str, Any] | None = None) -> dict[str, Any]:
    now = registry_tool.utc_time(None)
    nodes = []
    for wave_index, wave in enumerate(plan["waves"]):
        for node in wave["nodes"]:
            nodes.append({
                "nodeId": node["nodeId"], "waveIndex": wave_index,
                "status": "pending", "attempts": 0, "errorCode": None,
                "reconcileReportSha256": None,
                "currentActivationGeneration":
                    node["expectedActivationGeneration"], "updatedAt": now,
            })
    journal = {
        "schemaVersion": plan["schemaVersion"], "product": JOURNAL_PRODUCT,
        "rolloutId": plan["rolloutId"], "planSha256": plan_sha,
        "catalogId": plan["catalogId"],
        "candidateCatalogGeneration": plan["candidateCatalogGeneration"],
        "candidateCatalogSha256": plan["candidateCatalogSha256"],
        "status": "running", "currentWave": 0, "failedWave": None,
        "nodes": nodes, "createdAt": now, "updatedAt": now,
        "journalSha256": "0" * 64,
    }
    if plan["schemaVersion"] <= 4:
        if config_sha is None:
            raise ValueError("Fleet Executor config digest is unavailable")
        journal["executorConfigSha256"] = config_sha
    if plan["schemaVersion"] >= 2:
        journal.update({
            "gates": [{
                "waveId": wave["waveId"], "waveIndex": index,
                "status": "pending", "attempts": 0,
                "observationStartedAt": None, "evidenceSha256": None,
                "diagnosticCode": None, "updatedAt": now,
            } for index, wave in enumerate(plan["waves"])],
            "controlGeneration": 0, "controls": [],
        })
        if plan["schemaVersion"] <= 4:
            journal["gateConfigSha256"] = plan["gateConfigSha256"]
    if plan["schemaVersion"] >= 3:
        journal["authorizationAttempts"] = []
        if plan["schemaVersion"] <= 4:
            journal["controlAuthorizerConfigSha256"] = \
                plan["controlAuthorizerConfigSha256"]
    if plan["schemaVersion"] == 4:
        journal.update({
            "stateBackendConfigSha256": plan["stateBackendConfigSha256"],
            "artifactStoreConfigSha256": plan["artifactStoreConfigSha256"],
            "stateVersion": 0,
            "previousJournalSha256": None,
            "lastCoordinatorId": "uncommitted",
        })
    if plan["schemaVersion"] in {5, 6, 7}:
        journal.update({
            "adapterConfigResolverId": plan["adapterConfigResolverId"],
            "executorConfigRef": plan["executorConfigRef"],
            "gateConfigRef": plan["gateConfigRef"],
            "controlAuthorizerConfigRef":
                plan["controlAuthorizerConfigRef"],
            "stateBackendConfigRef": plan["stateBackendConfigRef"],
            "artifactStoreConfigRef": plan["artifactStoreConfigRef"],
            "stateVersion": 0,
            "previousJournalSha256": None,
            "lastCoordinatorId": "uncommitted",
        })
        if plan["schemaVersion"] in {6, 7}:
            if admission is None:
                raise ValueError("Fleet v6 admission evidence is unavailable")
            admission_tool.validate_summary(admission)
            journal.update({
                "adapterConformancePolicy":
                    plan["adapterConformancePolicy"],
                "admissions": [admission],
            })
            if plan["schemaVersion"] == 7:
                journal["adapterConformanceTrustPolicy"] = \
                    plan["adapterConformanceTrustPolicy"]
    journal["journalSha256"] = self_digest(journal)
    return journal


def record_admission(journal: dict[str, Any],
                     admission: dict[str, Any]) -> bool:
    admission_tool.validate_summary(admission)
    if journal["schemaVersion"] not in {6, 7}:
        raise ValueError("Adapter conformance admission requires Fleet v6+")
    existing = next((item for item in journal["admissions"]
                     if item["admissionId"] == admission["admissionId"]), None)
    if existing is not None:
        if existing != admission:
            # admittedAt is deliberately excluded from the stable identity.
            comparable = dict(admission)
            comparable["admittedAt"] = existing["admittedAt"]
            if existing != comparable:
                raise ValueError("Adapter conformance admission ID collision")
        return False
    if len(journal["admissions"]) >= 200:
        raise ValueError("Adapter conformance admission history is full")
    journal["admissions"].append(admission)
    return True


def load_admission(plan: dict[str, Any], args: argparse.Namespace) \
        -> admission_tool.Admission | None:
    bundle_path = getattr(args, "adapter_conformance_bundle", None)
    bundle_sha = getattr(
        args, "expected_adapter_conformance_bundle_sha256", None
    )
    trust_path = getattr(args, "adapter_conformance_trust_policy", None)
    trust_sha = getattr(
        args, "expected_adapter_conformance_trust_policy_sha256", None
    )
    if plan["schemaVersion"] not in {6, 7}:
        if bundle_path is not None or bundle_sha is not None:
            raise ValueError(
                "Adapter conformance admission arguments require a v6+ plan"
            )
        if trust_path is not None or trust_sha is not None:
            raise ValueError(
                "Adapter conformance trust arguments require a v7 plan"
            )
        return None
    if bundle_path is None or bundle_sha is None:
        raise ValueError(
            "Fleet v6+ requires a pinned Adapter conformance admission bundle"
        )
    if plan["schemaVersion"] == 6:
        if trust_path is not None or trust_sha is not None:
            raise ValueError(
                "Fleet v6 does not accept a conformance trust policy"
            )
        return admission_tool.Admission(
            bundle_path, bundle_sha, plan["adapterConformancePolicy"],
            rollout_id=plan["rolloutId"], catalog_id=plan["catalogId"],
        )
    if trust_path is None or trust_sha is None:
        raise ValueError(
            "Fleet v7 requires a pinned Adapter conformance trust policy"
        )
    trust = plan["adapterConformanceTrustPolicy"]
    return admission_tool.Admission(
        bundle_path, bundle_sha, plan["adapterConformancePolicy"],
        rollout_id=plan["rolloutId"], catalog_id=plan["catalogId"],
        trust_policy_path=trust_path,
        expected_trust_policy_sha256=trust_sha,
        expected_trust_policy_id=trust["policyId"],
        minimum_trust_policy_generation=trust["minimumGeneration"],
    )


def load_adapter_config_resolver(
        plan: dict[str, Any], args: argparse.Namespace,
        admission: admission_tool.Admission | None = None) \
        -> adapter_config_resolver_tool.ExternalCommandAdapterConfigResolver \
        | None:
    config_path = getattr(args, "adapter_config_resolver_config", None)
    expected_sha = getattr(
        args, "expected_adapter_config_resolver_config_sha256", None
    )
    if plan["schemaVersion"] not in {5, 6, 7}:
        if config_path is not None or expected_sha is not None:
            raise ValueError(
                "Adapter Config Resolver arguments require a v5+ plan"
            )
        return None
    if config_path is None or expected_sha is None:
        raise ValueError("Fleet v5+ requires a pinned Adapter Config Resolver")
    for label, value in (
            ("Executor config", getattr(args, "executor_config", None)),
            ("Executor config digest", getattr(
                args, "expected_executor_config_sha256", None)),
            ("state Backend config", getattr(
                args, "state_backend_config", None)),
            ("Artifact Store config", getattr(
                args, "artifact_store_config", None))):
        if value is not None:
            raise ValueError(f"Fleet v5+ rejects direct {label}")
    if admission is not None:
        resolver_config, _, resolver_config_sha = \
            adapter_config_resolver_tool.load_config(config_path, expected_sha)
        admission.precheck(
            "adapter-config-resolver", resolver_config, resolver_config_sha,
            adapter_id=plan["adapterConfigResolverId"],
            scope={"primaryId": None, "secondaryId": None},
        )
    resolver = adapter_config_resolver_tool.ExternalCommandAdapterConfigResolver(
        config_path, expected_sha
    )
    if resolver.resolver_id != plan["adapterConfigResolverId"]:
        raise ValueError("Fleet plan Adapter Config Resolver identity changed")
    if admission is not None:
        admission.postcheck(
            "adapter-config-resolver",
            resolver.capability_manifest_sha256,
        )
    return resolver


def resolve_adapter_config(
        resolver: adapter_config_resolver_tool.
            ExternalCommandAdapterConfigResolver,
        plan: dict[str, Any], field: str) \
        -> tuple[dict[str, Any], Path, str]:
    return resolver.resolve(
        plan[field], consumer_type="adapter-catalog-fleet",
        consumer_id=plan["rolloutId"], resource_id=plan["catalogId"],
    )


def load_execution_bindings(
        plan: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    admission = load_admission(plan, args)
    resolver = load_adapter_config_resolver(plan, args, admission)
    if resolver is None:
        executor_path = getattr(args, "executor_config", None)
        executor_sha = getattr(args, "expected_executor_config_sha256", None)
        if executor_path is None or executor_sha is None:
            raise ValueError("Fleet v1-v4 requires a pinned Executor config")
        config, config_path, config_sha = load_executor_config(
            executor_path, executor_sha
        )
        if (plan["executorConfigPath"] != str(config_path)
                or plan["executorConfigSha256"] != config_sha):
            raise ValueError("Fleet plan Executor config identity changed")
        gate_config = None
        if plan["schemaVersion"] >= 2:
            gate_config, gate_path, gate_sha = wave_gate_tool.load_config(
                plan["gateConfigPath"], plan["gateConfigSha256"]
            )
            if (plan["gateConfigPath"] != str(gate_path)
                    or plan["gateConfigSha256"] != gate_sha):
                raise ValueError("Fleet plan Wave Gate config identity changed")
        authorizer_config = None
        if plan["schemaVersion"] >= 3:
            authorizer_config, authorizer_path, authorizer_sha = \
                control_authorizer_tool.load_config(
                    plan["controlAuthorizerConfigPath"],
                    plan["controlAuthorizerConfigSha256"],
                )
            if (plan["controlAuthorizerConfigPath"] != str(authorizer_path)
                    or plan["controlAuthorizerConfigSha256"]
                        != authorizer_sha):
                raise ValueError(
                    "Fleet plan Control Authorizer config identity changed"
                )
        return {
            "admission": None,
            "resolver": None, "resolverCapabilitySha256": None,
            "executor": config, "executorSha256": config_sha,
            "gate": gate_config, "authorizer": authorizer_config,
            "state": None,
        }

    resolved_executor = resolve_adapter_config(
        resolver, plan, "executorConfigRef"
    )
    config, config_path, config_sha = load_executor_config(
        resolved_executor[1], resolved_executor[2]
    )
    if (config != resolved_executor[0]
            or config_path != resolved_executor[1]
            or config_sha != resolved_executor[2]):
        raise ValueError("resolved Fleet Executor config changed")
    if admission is not None:
        admission.precheck(
            "fleet-executor", config, config_sha,
            adapter_id=plan["executorConfigRef"]["adapterId"],
            scope={"primaryId": None, "secondaryId": None},
        )
    resolved_gate = resolve_adapter_config(resolver, plan, "gateConfigRef")
    gate_config, gate_path, gate_sha = wave_gate_tool.load_config(
        resolved_gate[1], resolved_gate[2]
    )
    if (gate_config != resolved_gate[0] or gate_path != resolved_gate[1]
            or gate_sha != resolved_gate[2]):
        raise ValueError("resolved Fleet Wave Gate config changed")
    if admission is not None:
        admission.precheck(
            "wave-gate", gate_config, gate_sha,
            adapter_id=plan["gateConfigRef"]["adapterId"],
            scope={"primaryId": None, "secondaryId": None},
        )
    resolved_authorizer = resolve_adapter_config(
        resolver, plan, "controlAuthorizerConfigRef"
    )
    authorizer_config, authorizer_path, authorizer_sha = \
        control_authorizer_tool.load_config(
            resolved_authorizer[1], resolved_authorizer[2]
        )
    if (authorizer_config != resolved_authorizer[0]
            or authorizer_path != resolved_authorizer[1]
            or authorizer_sha != resolved_authorizer[2]):
        raise ValueError("resolved Fleet Control Authorizer config changed")
    if admission is not None:
        admission.precheck(
            "control-authorizer", authorizer_config, authorizer_sha,
            adapter_id=plan["controlAuthorizerConfigRef"]["adapterId"],
            scope={"primaryId": None, "secondaryId": None},
        )
    resolved_backend = resolve_adapter_config(
        resolver, plan, "stateBackendConfigRef"
    )
    resolved_artifact = resolve_adapter_config(
        resolver, plan, "artifactStoreConfigRef"
    )
    if admission is not None:
        admission.precheck(
            "registry-leader-backend", resolved_backend[0],
            resolved_backend[2],
            adapter_id=plan["stateBackendConfigRef"]["adapterId"],
            scope={"primaryId": plan["rolloutId"],
                   "secondaryId": plan["catalogId"]},
        )
        admission.precheck(
            "artifact-store", resolved_artifact[0], resolved_artifact[2],
            adapter_id=plan["artifactStoreConfigRef"]["adapterId"],
            scope={"primaryId": plan["rolloutId"], "secondaryId": None},
        )
    return {
        "admission": admission,
        "resolver": resolver,
        "resolverCapabilitySha256": resolver.capability_manifest_sha256,
        "executor": config, "executorSha256": config_sha,
        "gate": gate_config, "authorizer": authorizer_config,
        "state": (resolved_backend, resolved_artifact),
    }


def remote_state_store(
        plan: dict[str, Any], plan_sha: str, args: argparse.Namespace,
        *, writable: bool,
        resolver: adapter_config_resolver_tool.
            ExternalCommandAdapterConfigResolver | None = None,
        resolved_state: tuple[
            tuple[dict[str, Any], Path, str],
            tuple[dict[str, Any], Path, str],
        ] | None = None) \
        -> fleet_state_store_tool.RemoteFleetStateStore | None:
    values = {
        "state Backend config": getattr(args, "state_backend_config", None),
        "Artifact Store config": getattr(args, "artifact_store_config", None),
    }
    coordinator_id = getattr(args, "coordinator_id", None)
    if plan["schemaVersion"] < 4:
        if any(value is not None for value in values.values()) \
                or coordinator_id is not None:
            raise ValueError("remote Fleet state arguments require a v4+ plan")
        return None
    if plan["schemaVersion"] in {5, 6, 7}:
        if any(value is not None for value in values.values()):
            raise ValueError("Fleet v5+ rejects direct State Store configs")
        if resolver is None or resolved_state is None:
            raise ValueError("Fleet v5+ State Store resolution is unavailable")
        if writable and coordinator_id is None:
            raise ValueError("Fleet v5+ state changes require --coordinator-id")
        state_backend, artifact_store = resolved_state
        return fleet_state_store_tool.RemoteFleetStateStore(
            state_backend_config=state_backend[1],
            state_backend_config_sha256=state_backend[2],
            artifact_store_config=artifact_store[1],
            artifact_store_config_sha256=artifact_store[2],
            rollout_id=plan["rolloutId"], catalog_id=plan["catalogId"],
            plan_sha256=plan_sha,
            expected_backend_id=plan["stateBackendConfigRef"]["adapterId"],
            expected_artifact_store_id=
                plan["artifactStoreConfigRef"]["adapterId"],
            coordinator_id=coordinator_id,
            adapter_config_resolver_id=resolver.resolver_id,
            state_backend_config_ref=plan["stateBackendConfigRef"],
            artifact_store_config_ref=plan["artifactStoreConfigRef"],
        )
    if any(value is None for value in values.values()):
        raise ValueError("Fleet v4 requires Backend and Artifact Store configs")
    if writable and coordinator_id is None:
        raise ValueError("Fleet v4 state changes require --coordinator-id")
    return fleet_state_store_tool.RemoteFleetStateStore(
        state_backend_config=values["state Backend config"],
        state_backend_config_sha256=plan["stateBackendConfigSha256"],
        artifact_store_config=values["Artifact Store config"],
        artifact_store_config_sha256=plan["artifactStoreConfigSha256"],
        rollout_id=plan["rolloutId"], catalog_id=plan["catalogId"],
        plan_sha256=plan_sha,
        expected_backend_id=plan["stateBackendId"],
        expected_artifact_store_id=plan["artifactStoreId"],
        coordinator_id=coordinator_id,
    )


def finalize_admission(
        bindings: dict[str, Any], state_store: fleet_state_store_tool.
            RemoteFleetStateStore | None,
        capability_sha: str, gate_capability_sha: str,
        authorizer_capability_sha: str,
        coordinator_id: str | None, *, create_summary: bool) \
        -> dict[str, Any] | None:
    admission = bindings.get("admission")
    if admission is None:
        return None
    if state_store is None:
        raise ValueError("Fleet v6 State Store is unavailable")
    admission.postcheck("fleet-executor", capability_sha)
    admission.postcheck("wave-gate", gate_capability_sha)
    admission.postcheck("control-authorizer", authorizer_capability_sha)
    admission.postcheck(
        "registry-leader-backend",
        state_store.backend_capability_manifest_sha256,
    )
    admission.postcheck(
        "artifact-store",
        state_store.artifact_store_capability_manifest_sha256,
    )
    if not create_summary:
        return None
    if coordinator_id is None:
        raise ValueError("Fleet v6 admission requires --coordinator-id")
    return admission.summary(coordinator_id)


def execute(args: argparse.Namespace, recover: bool) -> int:
    try:
        plan, _, plan_sha = load_plan(args.plan, args.expected_plan_sha256)
        bindings = load_execution_bindings(plan, args)
        config = bindings["executor"]
        config_sha = bindings["executorSha256"]
        capability_sha = negotiate(config)
        gate_config = bindings["gate"]
        gate_capability_sha = None
        authorizer_capability_sha = None
        if plan["schemaVersion"] >= 2:
            assert gate_config is not None
            gate_capability_sha = wave_gate_tool.negotiate(gate_config)
        if plan["schemaVersion"] >= 3:
            authorizer_config = bindings["authorizer"]
            assert authorizer_config is not None
            authorizer_capability_sha = \
                control_authorizer_tool.negotiate(authorizer_config)
        state_store = remote_state_store(
            plan, plan_sha, args, writable=True,
            resolver=bindings["resolver"], resolved_state=bindings["state"],
        )
        admission = finalize_admission(
            bindings, state_store, capability_sha,
            str(gate_capability_sha), str(authorizer_capability_sha),
            getattr(args, "coordinator_id", None), create_summary=True,
        )
        root = state_root(
            args.state_dir, create=plan["schemaVersion"] >= 4 or not recover
        )
        path: JournalTarget = state_store or journal_path(
            root, plan["rolloutId"]
        )
        lease = nullcontext() if state_store is not None \
            else FleetLease(root, plan["rolloutId"])
        with lease:
            try:
                journal = load_journal(path, plan)
            except FileNotFoundError:
                if recover:
                    raise
                journal = create_journal(
                    plan, plan_sha, config_sha, admission
                )
                write_journal(path, journal)
            if (journal["planSha256"] != plan_sha
                    or (plan["schemaVersion"] <= 4
                        and journal["executorConfigSha256"] != config_sha)):
                raise ValueError("Fleet rollout identity changed")
            if admission is not None and record_admission(journal, admission):
                write_journal(path, journal)
            drive(plan, config, path, journal, gate_config)
            report = report_for(
                journal, capability_sha, gate_capability_sha,
                authorizer_capability_sha, state_store,
                bindings["resolverCapabilitySha256"],
            )
            if args.report:
                package_tool.write_json(Path(args.report).resolve(), report)
        passed = journal["status"] == "committed"
        marker = "PASS" if passed else "ERROR"
        operation_name = "RECOVER" if recover else "RUN"
        print(
            f"PDR_ADAPTER_CATALOG_FLEET_{operation_name}_{marker} "
            f"rollout={journal['rolloutId']} status={journal['status']}"
        )
        return 0 if passed else 2
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        operation_name = "RECOVER" if recover else "RUN"
        print(
            f"PDR_ADAPTER_CATALOG_FLEET_{operation_name}_ERROR: {error}",
            file=sys.stderr,
        )
        return 2


def run_command(args: argparse.Namespace) -> int:
    return execute(args, False)


def recover_command(args: argparse.Namespace) -> int:
    return execute(args, True)


def validate_control_args(args: argparse.Namespace) -> None:
    if (package_tool.IDENTIFIER.fullmatch(str(args.operation_id)) is None
            or package_tool.IDENTIFIER.fullmatch(str(args.actor)) is None
            or type(args.expected_control_generation) is not int
            or args.expected_control_generation < 0
            or not isinstance(args.reason, str)
            or not 1 <= len(args.reason) <= 512
            or "\r" in args.reason or "\n" in args.reason):
        raise ValueError("Fleet control identity is malformed")


def control_command(args: argparse.Namespace, action: str) -> int:
    try:
        validate_control_args(args)
        plan, _, plan_sha = load_plan(args.plan, args.expected_plan_sha256)
        if plan["schemaVersion"] < 2:
            raise ValueError("Fleet control requires a Wave Gate plan")
        bindings = load_execution_bindings(plan, args)
        config = bindings["executor"]
        config_sha = bindings["executorSha256"]
        capability_sha = negotiate(config)
        gate_config = bindings["gate"]
        assert gate_config is not None
        gate_capability_sha = wave_gate_tool.negotiate(gate_config)
        authorizer_config = bindings["authorizer"]
        authorizer_capability_sha = None
        if plan["schemaVersion"] >= 3:
            assert authorizer_config is not None
            authorizer_capability_sha = \
                control_authorizer_tool.negotiate(authorizer_config)
        state_store = remote_state_store(
            plan, plan_sha, args, writable=True,
            resolver=bindings["resolver"], resolved_state=bindings["state"],
        )
        admission = finalize_admission(
            bindings, state_store, capability_sha,
            str(gate_capability_sha), str(authorizer_capability_sha),
            getattr(args, "coordinator_id", None), create_summary=True,
        )
        root = state_root(
            args.state_dir, create=plan["schemaVersion"] >= 4
        )
        path: JournalTarget = state_store or journal_path(
            root, plan["rolloutId"]
        )
        authorization_denied = False
        lease = nullcontext() if state_store is not None \
            else FleetLease(root, plan["rolloutId"])
        with lease:
            journal = load_journal(path, plan)
            if (journal["planSha256"] != plan_sha
                    or (plan["schemaVersion"] <= 4
                        and journal["executorConfigSha256"] != config_sha)):
                raise ValueError("Fleet rollout identity changed")
            if admission is not None and record_admission(journal, admission):
                write_journal(path, journal)
            existing = next((
                item for item in journal["controls"]
                if item["operationId"] == args.operation_id
            ), None)
            reason_sha256 = package_tool.sha256_bytes(args.reason.encode())
            existing_authorization = next((
                item for item in journal.get("authorizationAttempts", [])
                if item["operationId"] == args.operation_id
            ), None)
            if existing is not None:
                if (existing["action"] != action
                        or existing["actor"] != args.actor
                        or existing["reason"] != args.reason):
                    raise ValueError("Fleet control operation ID collision")
                if plan["schemaVersion"] >= 3 and (
                        existing_authorization is None
                        or existing_authorization["action"] != action
                        or existing_authorization["claimedActor"] != args.actor
                        or existing_authorization["reasonSha256"] != reason_sha256
                        or existing_authorization["controlGeneration"]
                            != args.expected_control_generation):
                    raise ValueError("Fleet authorization operation ID collision")
            elif existing_authorization is not None:
                if (existing_authorization["action"] != action
                        or existing_authorization["claimedActor"] != args.actor
                        or existing_authorization["reasonSha256"] != reason_sha256
                        or existing_authorization["controlGeneration"]
                            != args.expected_control_generation):
                    raise ValueError("Fleet authorization operation ID collision")
                if existing_authorization["decision"] != "deny":
                    raise ValueError("Fleet allowed authorization lacks control")
                authorization_denied = True
            else:
                if journal["controlGeneration"] != \
                        args.expected_control_generation:
                    raise ValueError("Fleet control generation changed")
                if journal["status"] != "paused":
                    raise ValueError("Fleet rollout is not paused")
                wave_index = journal["currentWave"]
                gate = journal["gates"][wave_index]
                if action == "resume" and gate["status"] != "paused":
                    raise ValueError("Fleet gate is not awaiting operator resume")
                authorization = None
                if plan["schemaVersion"] >= 3:
                    if len(journal["authorizationAttempts"]) >= 200:
                        raise ValueError("Fleet authorization history is full")
                    assert authorizer_config is not None
                    authorization = control_authorizer_tool.authorize(
                        authorizer_config,
                        rollout_id=plan["rolloutId"],
                        operation_id=args.operation_id, action=action,
                        claimed_actor=args.actor, reason_sha256=reason_sha256,
                        expected_control_generation=
                            args.expected_control_generation,
                        wave_id=plan["waves"][wave_index]["waveId"],
                        wave_index=wave_index, catalog_id=plan["catalogId"],
                        candidate_generation=plan["candidateCatalogGeneration"],
                        candidate_sha256=plan["candidateCatalogSha256"],
                        gate_evidence_sha256=gate["evidenceSha256"],
                    )
                    journal["authorizationAttempts"].append({
                        "authorizationId": authorization["authorizationId"],
                        "operationId": args.operation_id, "action": action,
                        "claimedActor": args.actor,
                        "reasonSha256": reason_sha256,
                        "decision": authorization["decision"],
                        "principalId": authorization["principalId"],
                        "evidenceSha256": authorization["evidenceSha256"],
                        "diagnosticCode": authorization["diagnosticCode"],
                        "controlGeneration": journal["controlGeneration"],
                        "waveIndex": wave_index,
                        "at": registry_tool.utc_time(None),
                    })
                    if not authorization["allowed"]:
                        authorization_denied = True
                        write_journal(path, journal)
                # A denial is terminal for this operation ID, but leaves the
                # rollout durably paused and available for a fresh approval.
                if not authorization_denied:
                    principal = (
                        authorization["principalId"]
                        if authorization is not None else args.actor
                    )
                    generation = journal["controlGeneration"] + 1
                    control = {
                        "generation": generation,
                        "operationId": args.operation_id, "action": action,
                        "actor": principal, "reason": args.reason,
                        "waveIndex": wave_index,
                        "at": registry_tool.utc_time(None),
                    }
                    if authorization is not None:
                        control.update({
                            "authorizationId": authorization["authorizationId"],
                            "authorizationEvidenceSha256":
                                authorization["evidenceSha256"],
                        })
                    journal["controls"].append(control)
                    journal["controlGeneration"] = generation
                    if action == "resume":
                        gate["status"] = "pending"
                        gate["diagnosticCode"] = None
                        gate["updatedAt"] = registry_tool.utc_time(None)
                        journal["status"] = "running"
                        write_journal(path, journal)
                        drive(plan, config, path, journal, gate_config)
                    else:
                        gate["status"] = "failed"
                        gate["diagnosticCode"] = "operator-abort"
                        gate["updatedAt"] = registry_tool.utc_time(None)
                        journal["failedWave"] = wave_index
                        journal["status"] = "rolling-back"
                        write_journal(path, journal)
                        rollback_committed(plan, config, path, journal)
            report = report_for(
                journal, capability_sha, gate_capability_sha,
                authorizer_capability_sha, state_store,
                bindings["resolverCapabilitySha256"],
            )
            if args.report:
                package_tool.write_json(Path(args.report).resolve(), report)
        succeeded = not authorization_denied and (
            journal["status"] == "committed" if action == "resume"
            else journal["status"] == "rolled-back"
        )
        marker = "PASS" if succeeded else "ERROR"
        print(
            f"PDR_ADAPTER_CATALOG_FLEET_{action.upper()}_{marker} "
            f"rollout={journal['rolloutId']} status={journal['status']}"
        )
        return 0 if succeeded else 2
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(
            f"PDR_ADAPTER_CATALOG_FLEET_{action.upper()}_ERROR: {error}",
            file=sys.stderr,
        )
        return 2


def resume_command(args: argparse.Namespace) -> int:
    return control_command(args, "resume")


def abort_command(args: argparse.Namespace) -> int:
    return control_command(args, "abort")


def status_command(args: argparse.Namespace) -> int:
    try:
        plan, _, plan_sha = load_plan(args.plan, args.expected_plan_sha256)
        bindings = None
        resolver = None
        resolved_state = None
        if plan["schemaVersion"] in {6, 7}:
            bindings = load_execution_bindings(plan, args)
            resolver = bindings["resolver"]
            capability_sha = negotiate(bindings["executor"])
            gate_capability_sha = wave_gate_tool.negotiate(bindings["gate"])
            authorizer_capability_sha = control_authorizer_tool.negotiate(
                bindings["authorizer"]
            )
            resolved_state = bindings["state"]
        else:
            resolver = load_adapter_config_resolver(plan, args)
            if resolver is not None:
                resolved_state = (
                    resolve_adapter_config(
                        resolver, plan, "stateBackendConfigRef"
                    ),
                    resolve_adapter_config(
                        resolver, plan, "artifactStoreConfigRef"
                    ),
                )
        state_store = remote_state_store(
            plan, plan_sha, args, writable=False,
            resolver=resolver, resolved_state=resolved_state,
        )
        if plan["schemaVersion"] in {6, 7}:
            assert bindings is not None
            finalize_admission(
                bindings, state_store, capability_sha,
                gate_capability_sha, authorizer_capability_sha,
                None, create_summary=False,
            )
        root = state_root(
            args.state_dir, create=plan["schemaVersion"] >= 4
        )
        path: JournalTarget = state_store or journal_path(
            root, plan["rolloutId"]
        )
        journal = load_journal(path, plan)
        if journal["planSha256"] != plan_sha:
            raise ValueError("Fleet rollout identity changed")
        counts = {
            status: sum(node["status"] == status for node in journal["nodes"])
            for status in NODE_STATUSES
        }
        report = {
            "schemaVersion": journal["schemaVersion"], "product": STATUS_PRODUCT,
            "rolloutId": journal["rolloutId"], "status": journal["status"],
            "terminal": journal["status"] in {"committed", "rolled-back"},
            "currentWave": journal["currentWave"],
            "failedWave": journal["failedWave"], "nodeCounts": counts,
            "journalSha256": journal["journalSha256"],
            "observedAt": registry_tool.utc_time(None),
        }
        if journal["schemaVersion"] >= 2:
            report.update({
                "gateCounts": {
                    status: sum(gate["status"] == status
                                for gate in journal["gates"])
                    for status in GATE_STATUSES
                },
                "activeGate": (
                    journal["gates"][journal["currentWave"]]
                    if journal["currentWave"] < len(journal["gates"])
                    else None
                ),
                "controlGeneration": journal["controlGeneration"],
            })
            if journal["schemaVersion"] >= 3:
                report["authorizationCounts"] = {
                    decision: sum(
                        item["decision"] == decision
                        for item in journal["authorizationAttempts"]
                    ) for decision in ("allow", "deny")
                }
            if journal["schemaVersion"] >= 4:
                if state_store is None:
                    raise ValueError("Fleet remote State Store is unavailable")
                report.update({
                    "stateVersion": journal["stateVersion"],
                    "lastCoordinatorId": journal["lastCoordinatorId"],
                    "stateBackendCapabilityManifestSha256":
                        state_store.backend_capability_manifest_sha256,
                    "artifactStoreCapabilityManifestSha256":
                        state_store.artifact_store_capability_manifest_sha256,
                })
                if journal["schemaVersion"] in {5, 6, 7}:
                    assert resolver is not None
                    report[
                        "adapterConfigResolverCapabilityManifestSha256"
                    ] = resolver.capability_manifest_sha256
                if journal["schemaVersion"] in {6, 7}:
                    report.update({
                        "adapterConformanceAdmissionId":
                            journal["admissions"][-1]["admissionId"],
                        "adapterConformanceAdmissionCount":
                            len(journal["admissions"]),
                    })
                    if journal["schemaVersion"] == 7:
                        latest = journal["admissions"][-1]
                        report.update({
                            "adapterConformanceTrustPolicyId":
                                latest["trustPolicyId"],
                            "adapterConformanceTrustPolicyGeneration":
                                latest["trustPolicyGeneration"],
                            "adapterConformanceTrustPolicySha256":
                                latest["trustPolicySha256"],
                        })
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print(
            "PDR_ADAPTER_CATALOG_FLEET_STATUS_PASS "
            f"rollout={journal['rolloutId']} status={journal['status']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_FLEET_STATUS_ERROR: {error}", file=sys.stderr)
        return 2


def add_execution_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--plan", required=True)
    command.add_argument("--expected-plan-sha256", required=True)
    command.add_argument("--executor-config")
    command.add_argument("--expected-executor-config-sha256")
    command.add_argument("--adapter-config-resolver-config")
    command.add_argument(
        "--expected-adapter-config-resolver-config-sha256"
    )
    command.add_argument("--adapter-conformance-bundle")
    command.add_argument(
        "--expected-adapter-conformance-bundle-sha256"
    )
    command.add_argument("--adapter-conformance-trust-policy")
    command.add_argument(
        "--expected-adapter-conformance-trust-policy-sha256"
    )
    command.add_argument("--state-dir", required=True)
    command.add_argument("--state-backend-config")
    command.add_argument("--artifact-store-config")
    command.add_argument("--coordinator-id")
    command.add_argument("--report")


def add_control_arguments(command: argparse.ArgumentParser) -> None:
    add_execution_arguments(command)
    command.add_argument("--expected-control-generation", type=int, required=True)
    command.add_argument("--operation-id", required=True)
    command.add_argument("--actor", required=True)
    command.add_argument("--reason", required=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    run = commands.add_parser("run")
    add_execution_arguments(run)
    run.set_defaults(handler=run_command)
    recover = commands.add_parser("recover")
    add_execution_arguments(recover)
    recover.set_defaults(handler=recover_command)
    resume = commands.add_parser("resume")
    add_control_arguments(resume)
    resume.set_defaults(handler=resume_command)
    abort = commands.add_parser("abort")
    add_control_arguments(abort)
    abort.set_defaults(handler=abort_command)
    status = commands.add_parser("status")
    status.add_argument("--plan", required=True)
    status.add_argument("--expected-plan-sha256", required=True)
    status.add_argument("--state-dir", required=True)
    status.add_argument("--state-backend-config")
    status.add_argument("--artifact-store-config")
    status.add_argument("--coordinator-id")
    status.add_argument("--adapter-config-resolver-config")
    status.add_argument(
        "--expected-adapter-config-resolver-config-sha256"
    )
    status.add_argument("--adapter-conformance-bundle")
    status.add_argument(
        "--expected-adapter-conformance-bundle-sha256"
    )
    status.add_argument("--adapter-conformance-trust-policy")
    status.add_argument(
        "--expected-adapter-conformance-trust-policy-sha256"
    )
    status.add_argument("--report")
    status.set_defaults(handler=status_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
