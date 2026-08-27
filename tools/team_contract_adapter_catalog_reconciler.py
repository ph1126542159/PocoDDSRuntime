#!/usr/bin/env python3
"""Recoverable Adapter Catalog rollout coordinator with health-gated rollback."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import process_file_lease as process_lease
import team_contract_adapter_catalog as catalog_tool
import team_contract_adapter_catalog_state as state_tool
import team_contract_adapter_runtime as adapter_runtime
import team_contract_package as package_tool
import team_contract_registry as registry_tool


CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogReconcilerConfig"
CAPABILITY_REQUEST_PRODUCT = (
    "PocoDDSRuntimeTeamContractAdapterCatalogReconcilerCapabilityRequest"
)
CAPABILITY_MANIFEST_PRODUCT = (
    "PocoDDSRuntimeTeamContractAdapterCatalogReconcilerCapabilityManifest"
)
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogReconcilerRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogReconcilerResponse"
JOURNAL_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogReconcileJournal"
REPORT_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogReconcileReport"
STATUS_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogReconcileStatus"
REQUIRED_CAPABILITIES = [
    "abort", "activate", "bounded-drain", "commit", "health-gate",
    "idempotent-operations", "prepare", "rollback",
]
TERMINAL_STATUSES = {"committed", "aborted", "rolled-back"}
STATUSES = {
    "preparing", "prepared", "draining", "drained", "switching", "switched",
    "activating", "activated", "health-checking", "healthy", "committing",
    "committed", "aborting", "aborted", "abort-failed", "rolling-back",
    "catalog-rolled-back", "rollback-hook", "rolled-back", "rollback-failed",
}
HOOK_STATES = {
    "prepare": "prepared", "drain": "drained", "activate": "activated",
    "commit": "committed", "abort": "aborted", "rollback": "rolled-back",
}


def validate_config(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "reconcilerId", "kind", "protocolMajor",
        "minimumProtocolMinor", "requiredCapabilities", "executable",
        "executableSha256", "arguments", "artifactPins",
        "environmentVariables", "optionalEnvironmentVariables",
        "timeoutSeconds", "maxResponseBytes", "healthAttempts",
        "healthIntervalMilliseconds",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CONFIG_PRODUCT
            or package_tool.IDENTIFIER.fullmatch(
                str(document.get("reconcilerId", ""))) is None
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
            or not 1 <= document["timeoutSeconds"] <= 60
            or type(document.get("maxResponseBytes")) is not int
            or not 1024 <= document["maxResponseBytes"] <= 1024 * 1024
            or type(document.get("healthAttempts")) is not int
            or not 1 <= document["healthAttempts"] <= 100
            or type(document.get("healthIntervalMilliseconds")) is not int
            or not 0 <= document["healthIntervalMilliseconds"] <= 30000):
        raise ValueError("Adapter Catalog Reconciler config is malformed")
    adapter_runtime.validate_artifact_pins(document["artifactPins"], "reconciler")
    adapter_runtime.validate_environment_policy(
        document["environmentVariables"],
        optional=document["optionalEnvironmentVariables"], label="reconciler",
    )


def load_config(path_value: str | Path, expected_sha: str) \
        -> tuple[dict[str, Any], Path, str]:
    config, path, digest = adapter_runtime.load_pinned_json(
        path_value, expected_sha, "Adapter Catalog Reconciler config",
        validate_config,
    )
    adapter_runtime.revalidate_artifacts(config, "reconciler")
    return config, path, digest


def hook_environment(config: dict[str, Any]) -> dict[str, str]:
    return adapter_runtime.isolated_environment(
        config["environmentVariables"],
        optional=config["optionalEnvironmentVariables"],
        require_required=True, label="Adapter Catalog Reconciler",
    )


def invoke_hook(config: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    adapter_runtime.revalidate_artifacts(config, "reconciler")
    return adapter_runtime.invoke_json(
        [str(Path(config["executable"]).resolve()), *config["arguments"]],
        request, environment=hook_environment(config),
        timeout_seconds=config["timeoutSeconds"],
        max_response_bytes=config["maxResponseBytes"],
        label="Adapter Catalog Reconciler hook", expose_stderr=False,
    )


def negotiate(config: dict[str, Any]) -> str:
    request = {
        "schemaVersion": 1, "product": CAPABILITY_REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()),
        "reconcilerId": config["reconcilerId"],
    }
    response = invoke_hook(config, request)
    fields = {
        "schemaVersion", "product", "requestId", "reconcilerId",
        "implementationId", "protocolMajor", "protocolMinor", "capabilities",
    }
    if (not isinstance(response, dict) or set(response) != fields
            or response.get("schemaVersion") != 1
            or response.get("product") != CAPABILITY_MANIFEST_PRODUCT
            or response.get("requestId") != request["requestId"]
            or response.get("reconcilerId") != config["reconcilerId"]
            or package_tool.IDENTIFIER.fullmatch(
                str(response.get("implementationId", ""))) is None
            or type(response.get("protocolMajor")) is not int
            or type(response.get("protocolMinor")) is not int
            or not isinstance(response.get("capabilities"), list)
            or response["capabilities"] != sorted(set(response["capabilities"]))
            or any(adapter_runtime.CAPABILITY_ID.fullmatch(str(item)) is None
                   for item in response["capabilities"])):
        raise ValueError("Reconciler capability manifest is malformed")
    adapter_runtime.enforce_capability_policy(config, response, "reconciler")
    return adapter_runtime.capability_digest(response, "reconcilerId")


def validate_response(response: Any, request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "transactionId",
        "reconcilerId", "operation", "accepted", "state",
        "pendingOperations", "diagnosticCode",
    }
    if (not isinstance(response, dict) or set(response) != fields
            or response.get("schemaVersion") != 1
            or response.get("product") != RESPONSE_PRODUCT
            or any(response.get(name) != request[name] for name in (
                "requestId", "transactionId", "reconcilerId", "operation"))
            or type(response.get("accepted")) is not bool
            or not isinstance(response.get("state"), str)
            or type(response.get("pendingOperations")) is not int
            or response["pendingOperations"] < 0
            or (response.get("diagnosticCode") is not None
                and package_tool.IDENTIFIER.fullmatch(
                    str(response["diagnosticCode"])) is None)):
        raise ValueError("Reconciler hook response is malformed or mismatched")


def journal_request(journal: dict[str, Any], config: dict[str, Any],
                    operation: str, attempt: int,
                    current_generation: int) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()),
        "transactionId": journal["transactionId"],
        "reconcilerId": config["reconcilerId"], "operation": operation,
        "catalogId": journal["catalogId"],
        "sourceActivationGeneration": journal["sourceActivationGeneration"],
        "sourceCatalogGeneration": journal["sourceCatalogGeneration"],
        "sourceCatalogSha256": journal["sourceCatalogSha256"],
        "candidateCatalogGeneration": journal["candidateCatalogGeneration"],
        "candidateCatalogSha256": journal["candidateCatalogSha256"],
        "currentActivationGeneration": current_generation, "attempt": attempt,
    }


def operation(config: dict[str, Any], journal: dict[str, Any], name: str,
              current_generation: int, attempt: int = 0) -> dict[str, Any]:
    request = journal_request(journal, config, name, attempt, current_generation)
    response = invoke_hook(config, request)
    validate_response(response, request)
    if name == "health":
        if response["state"] not in {"healthy", "unhealthy"}:
            raise ValueError("Reconciler health response state is invalid")
        if response["accepted"] != (response["state"] == "healthy"):
            raise ValueError("Reconciler health acceptance is inconsistent")
        return response
    if (not response["accepted"] or response["state"] != HOOK_STATES[name]
            or (name == "drain" and response["pendingOperations"] != 0)):
        code = response["diagnosticCode"] or f"{name}-rejected"
        raise RuntimeError(code)
    return response


def self_digest(document: dict[str, Any]) -> str:
    return package_tool.sha256_bytes(package_tool.json_bytes({
        key: value for key, value in document.items() if key != "journalSha256"
    }))


def validate_journal(journal: Any) -> None:
    fields = {
        "schemaVersion", "product", "transactionId", "reconcilerId",
        "configSha256", "catalogId", "sourceActivationGeneration",
        "sourceCatalogGeneration", "sourceCatalogSha256",
        "candidateCatalogGeneration", "candidateCatalogSha256", "actor",
        "reason", "status", "switchedGeneration", "rollbackGeneration",
        "healthAttempt", "lastOperation", "errorCode", "createdAt", "updatedAt",
        "journalSha256",
    }
    if (not isinstance(journal, dict) or set(journal) != fields
            or journal.get("schemaVersion") != 1
            or journal.get("product") != JOURNAL_PRODUCT
            or any(package_tool.IDENTIFIER.fullmatch(
                str(journal.get(name, ""))) is None
                for name in ("transactionId", "reconcilerId", "catalogId", "actor"))
            or any(package_tool.SHA256.fullmatch(
                str(journal.get(name, ""))) is None
                for name in ("configSha256", "sourceCatalogSha256",
                             "candidateCatalogSha256", "journalSha256"))
            or type(journal.get("sourceActivationGeneration")) is not int
            or journal["sourceActivationGeneration"] < 1
            or type(journal.get("sourceCatalogGeneration")) is not int
            or journal["sourceCatalogGeneration"] < 1
            or type(journal.get("candidateCatalogGeneration")) is not int
            or journal["candidateCatalogGeneration"] <= journal["sourceCatalogGeneration"]
            or journal.get("status") not in STATUSES
            or (journal.get("switchedGeneration") is not None
                and (type(journal["switchedGeneration"]) is not int
                     or journal["switchedGeneration"] < 2))
            or (journal.get("rollbackGeneration") is not None
                and (type(journal["rollbackGeneration"]) is not int
                     or journal["rollbackGeneration"] < 3))
            or type(journal.get("healthAttempt")) is not int
            or not 0 <= journal["healthAttempt"] <= 100
            or (journal.get("lastOperation") is not None
                and journal["lastOperation"] not in {
                    "prepare", "drain", "switch", "activate", "health",
                    "commit", "abort", "rollback",
                })
            or (journal.get("errorCode") is not None
                and package_tool.IDENTIFIER.fullmatch(
                    str(journal["errorCode"])) is None)
            or not isinstance(journal.get("reason"), str)
            or not 1 <= len(journal["reason"]) <= 512
            or "\r" in journal["reason"] or "\n" in journal["reason"]
            or journal["journalSha256"] != self_digest(journal)):
        raise ValueError("Adapter Catalog reconcile journal is malformed")
    created = package_tool.parse_time(
        journal.get("createdAt"), "reconcile createdAt"
    )
    updated = package_tool.parse_time(
        journal.get("updatedAt"), "reconcile updatedAt"
    )
    if updated < created:
        raise ValueError("Adapter Catalog reconcile journal time moved backwards")
    pre_switch = {
        "preparing", "prepared", "draining", "drained", "switching",
        "aborting", "aborted", "abort-failed",
    }
    after_switch = STATUSES - pre_switch
    if (journal["status"] in pre_switch
            and (journal["switchedGeneration"] is not None
                 or journal["rollbackGeneration"] is not None)):
        raise ValueError("pre-switch reconcile journal contains switch evidence")
    if (journal["status"] in after_switch
            and journal["switchedGeneration"]
                != journal["sourceActivationGeneration"] + 1):
        raise ValueError("post-switch reconcile journal lacks exact switch evidence")
    after_catalog_rollback = {
        "catalog-rolled-back", "rollback-hook", "rolled-back",
    }
    if (journal["status"] in after_catalog_rollback
            and journal["rollbackGeneration"]
                != journal["switchedGeneration"] + 1):
        raise ValueError("reconcile journal lacks exact rollback evidence")
    if (journal["rollbackGeneration"] is not None
            and journal["rollbackGeneration"]
                != journal["switchedGeneration"] + 1):
        raise ValueError("reconcile rollback generation is inconsistent")
    if (journal["status"] == "committed"
            and (journal["errorCode"] is not None
                 or journal["rollbackGeneration"] is not None)):
        raise ValueError("committed reconcile journal contains failure evidence")
    if journal["status"] in {"aborted", "rolled-back"} \
            and journal["errorCode"] is None:
        raise ValueError("failed reconcile terminal lacks a stable error code")


def transaction_root(value: str | Path, create: bool = False) -> Path:
    return state_tool.state_root(value, create=create)


def transaction_directory(root: Path, transaction_id: str) -> Path:
    return state_tool.safe_member(
        root, f"transactions/{transaction_id}", "Reconciler transaction"
    )


def journal_path(root: Path, transaction_id: str) -> Path:
    return state_tool.safe_member(
        root, f"transactions/{transaction_id}/journal.json",
        "Reconciler journal",
    )


def candidate_path(root: Path, transaction_id: str) -> Path:
    return state_tool.safe_member(
        root, f"transactions/{transaction_id}/candidate.catalog.json",
        "Reconciler candidate",
    )


def write_journal(path: Path, journal: dict[str, Any]) -> None:
    journal["updatedAt"] = registry_tool.utc_time(None)
    journal["journalSha256"] = self_digest(journal)
    package_tool.write_json(path, journal)


def load_journal(path: Path) -> dict[str, Any]:
    journal = state_tool.load_json(path, "Adapter Catalog reconcile journal")
    validate_journal(journal)
    return journal


class ReconcileLease(process_lease.ProcessFileLease):
    def __init__(self, root: Path, transaction_id: str) -> None:
        super().__init__(
            root / ".adapter-catalog-reconcile.lock",
            root / ".adapter-catalog-reconcile.epoch.json",
            "team-contract-adapter-catalog-reconciler",
            {"transactionId": transaction_id},
        )

    def acquire(self) -> "ReconcileLease":
        try:
            super().acquire()
            return self
        except process_lease.LeaseBusyError as error:
            raise ValueError("another Adapter Catalog reconcile is active") from error


def transition(path: Path, journal: dict[str, Any], status: str,
               operation_name: str | None = None,
               error_code: str | None = None) -> None:
    if status not in STATUSES:
        raise ValueError("unsupported Adapter Catalog reconcile status")
    journal["status"] = status
    journal["lastOperation"] = operation_name
    journal["errorCode"] = error_code
    write_journal(path, journal)


def stable_error(error: BaseException, fallback: str) -> str:
    message = str(error)
    if package_tool.IDENTIFIER.fullmatch(message):
        return message
    return fallback


def activation_report_path(root: Path, transaction_id: str) -> Path:
    return transaction_directory(root, transaction_id) / "activation.json"


def rollback_report_path(root: Path, transaction_id: str) -> Path:
    return transaction_directory(root, transaction_id) / "rollback.json"


def activate_catalog(state_dir: Path, root: Path, journal: dict[str, Any]) -> int:
    report_path = activation_report_path(root, journal["transactionId"])
    args = argparse.Namespace(
        catalog=str(candidate_path(root, journal["transactionId"])),
        expected_catalog_sha256=journal["candidateCatalogSha256"],
        state_dir=str(state_dir),
        expected_generation=journal["sourceActivationGeneration"],
        operation_id=f"{journal['transactionId']}.activate",
        actor=journal["actor"], reason=journal["reason"], report=str(report_path),
    )
    if state_tool.activate_command(args) != 0:
        pointer, current, _ = state_tool.read_current(state_dir)
        chain = state_tool.verify_chain(state_dir, pointer, current)
        matches = [
            state for _, state in chain
            if state["operationId"] == args.operation_id
            and state["action"] == "activate"
            and state["catalogSha256"] == journal["candidateCatalogSha256"]
        ]
        if len(matches) != 1:
            raise RuntimeError("catalog-switch-failed")
        return matches[0]["generation"]
    report = state_tool.load_json(report_path, "Catalog activation report")
    if (report.get("product") != state_tool.OPERATION_PRODUCT
            or report.get("action") != "activate"
            or report.get("catalogSha256") != journal["candidateCatalogSha256"]):
        raise ValueError("Catalog activation report is mismatched")
    return report["generation"]


def rollback_catalog(state_dir: Path, root: Path, journal: dict[str, Any]) -> int:
    report_path = rollback_report_path(root, journal["transactionId"])
    args = argparse.Namespace(
        state_dir=str(state_dir),
        expected_generation=journal["switchedGeneration"],
        operation_id=f"{journal['transactionId']}.rollback",
        actor=journal["actor"],
        reason=(
            f"automatic rollback {journal['transactionId']}: {journal['reason']}"
        )[:512],
        to_generation=journal["sourceActivationGeneration"],
        report=str(report_path),
    )
    if state_tool.rollback_command(args) != 0:
        pointer, current, _ = state_tool.read_current(state_dir)
        chain = state_tool.verify_chain(state_dir, pointer, current)
        matches = [
            state for _, state in chain
            if state["operationId"] == args.operation_id
            and state["action"] == "rollback"
            and state["catalogSha256"] == journal["sourceCatalogSha256"]
        ]
        if len(matches) != 1:
            raise RuntimeError("catalog-rollback-failed")
        return matches[0]["generation"]
    report = state_tool.load_json(report_path, "Catalog rollback report")
    if (report.get("product") != state_tool.OPERATION_PRODUCT
            or report.get("action") != "rollback"
            or report.get("catalogSha256") != journal["sourceCatalogSha256"]):
        raise ValueError("Catalog rollback report is mismatched")
    return report["generation"]


def abort_before_switch(config: dict[str, Any], path: Path,
                        journal: dict[str, Any], error_code: str) -> None:
    transition(path, journal, "aborting", "abort", error_code)
    try:
        operation(
            config, journal, "abort", journal["sourceActivationGeneration"]
        )
        transition(path, journal, "aborted", "abort", error_code)
    except (OSError, ValueError, RuntimeError) as error:
        transition(
            path, journal, "abort-failed", "abort",
            stable_error(error, "abort-failed"),
        )


def automatic_rollback(config: dict[str, Any], state_dir: Path, root: Path,
                       path: Path, journal: dict[str, Any],
                       error_code: str) -> None:
    transition(path, journal, "rolling-back", "rollback", error_code)
    try:
        journal["rollbackGeneration"] = rollback_catalog(
            state_dir, root, journal
        )
        transition(path, journal, "catalog-rolled-back", "rollback", error_code)
        transition(path, journal, "rollback-hook", "rollback", error_code)
        operation(
            config, journal, "rollback", journal["rollbackGeneration"]
        )
        transition(path, journal, "rolled-back", "rollback", error_code)
    except (OSError, ValueError, RuntimeError) as error:
        transition(
            path, journal, "rollback-failed", "rollback",
            stable_error(error, "rollback-failed"),
        )


def resume_rollback(config: dict[str, Any], state_dir: Path, root: Path,
                    path: Path, journal: dict[str, Any]) -> None:
    original_error = journal["errorCode"] or "rollout-failed"
    automatic_rollback(
        config, state_dir, root, path, journal, original_error
    )


def drive(config: dict[str, Any], state_dir: Path, root: Path,
          path: Path, journal: dict[str, Any]) -> None:
    if journal["status"] in {"rolling-back", "catalog-rolled-back",
                             "rollback-hook", "rollback-failed"}:
        resume_rollback(config, state_dir, root, path, journal)
        return
    if journal["status"] in {"aborting", "abort-failed"}:
        abort_before_switch(
            config, path, journal, journal["errorCode"] or "rollout-aborted"
        )
        return
    if journal["status"] in TERMINAL_STATUSES:
        return
    try:
        if journal["status"] == "preparing":
            operation(
                config, journal, "prepare",
                journal["sourceActivationGeneration"],
            )
            transition(path, journal, "prepared", "prepare")
        if journal["status"] in {"prepared", "draining"}:
            transition(path, journal, "draining", "drain")
            operation(
                config, journal, "drain",
                journal["sourceActivationGeneration"],
            )
            transition(path, journal, "drained", "drain")
        if journal["status"] in {"drained", "switching"}:
            transition(path, journal, "switching", "switch")
            journal["switchedGeneration"] = activate_catalog(
                state_dir, root, journal
            )
            transition(path, journal, "switched", "switch")
    except (OSError, ValueError, RuntimeError) as error:
        abort_before_switch(
            config, path, journal, stable_error(error, "pre-switch-failed")
        )
        return
    try:
        if journal["status"] in {"switched", "activating"}:
            transition(path, journal, "activating", "activate")
            operation(
                config, journal, "activate", journal["switchedGeneration"]
            )
            transition(path, journal, "activated", "activate")
        if journal["status"] in {"activated", "health-checking"}:
            transition(path, journal, "health-checking", "health")
            healthy = False
            while journal["healthAttempt"] < config["healthAttempts"]:
                journal["healthAttempt"] += 1
                write_journal(path, journal)
                response = operation(
                    config, journal, "health", journal["switchedGeneration"],
                    journal["healthAttempt"],
                )
                if response["accepted"]:
                    healthy = True
                    break
                if journal["healthAttempt"] < config["healthAttempts"]:
                    time.sleep(config["healthIntervalMilliseconds"] / 1000)
            if not healthy:
                raise RuntimeError("health-gate-failed")
            transition(path, journal, "healthy", "health")
        if journal["status"] in {"healthy", "committing"}:
            transition(path, journal, "committing", "commit")
            operation(
                config, journal, "commit", journal["switchedGeneration"]
            )
            transition(path, journal, "committed", "commit")
    except (OSError, ValueError, RuntimeError) as error:
        automatic_rollback(
            config, state_dir, root, path, journal,
            stable_error(error, "post-switch-failed"),
        )


def report_for(journal: dict[str, Any], capability_sha: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": REPORT_PRODUCT,
        "passed": journal["status"] == "committed",
        "transactionId": journal["transactionId"],
        "reconcilerId": journal["reconcilerId"],
        "catalogId": journal["catalogId"], "status": journal["status"],
        "sourceActivationGeneration": journal["sourceActivationGeneration"],
        "candidateCatalogGeneration": journal["candidateCatalogGeneration"],
        "candidateCatalogSha256": journal["candidateCatalogSha256"],
        "switchedGeneration": journal["switchedGeneration"],
        "rollbackGeneration": journal["rollbackGeneration"],
        "healthAttempts": journal["healthAttempt"],
        "errorCode": journal["errorCode"],
        "capabilityManifestSha256": capability_sha,
        "journalSha256": journal["journalSha256"],
        "reportedAt": registry_tool.utc_time(None),
    }


def validate_run_identity(args: argparse.Namespace) -> None:
    if (package_tool.IDENTIFIER.fullmatch(str(args.transaction_id)) is None
            or package_tool.IDENTIFIER.fullmatch(
                f"{args.transaction_id}.activate") is None
            or package_tool.IDENTIFIER.fullmatch(
                f"{args.transaction_id}.rollback") is None
            or package_tool.IDENTIFIER.fullmatch(str(args.actor)) is None
            or not isinstance(args.reason, str)
            or not 1 <= len(args.reason) <= 512
            or "\r" in args.reason or "\n" in args.reason):
        raise ValueError("Adapter Catalog reconcile identity is malformed")


def run_command(args: argparse.Namespace) -> int:
    try:
        validate_run_identity(args)
        config, _, config_sha = load_config(
            args.config, args.expected_config_sha256
        )
        capability_sha = negotiate(config)
        root = transaction_root(args.transaction_dir, create=True)
        state_dir = state_tool.state_root(args.state_dir)
        path = journal_path(root, args.transaction_id)
        with ReconcileLease(root, args.transaction_id):
            if path.exists():
                journal = load_journal(path)
                if (journal["configSha256"] != config_sha
                        or journal["reconcilerId"] != config["reconcilerId"]
                        or journal["actor"] != args.actor
                        or journal["reason"] != args.reason
                        or journal["candidateCatalogSha256"]
                            != args.expected_catalog_sha256
                        or journal["sourceActivationGeneration"]
                            != args.expected_generation):
                    raise ValueError("Adapter Catalog reconcile transaction ID collision")
            else:
                pointer, source, _, _, _ = state_tool.current_context(state_dir)
                if pointer["generation"] != args.expected_generation:
                    raise ValueError(
                        "Adapter Catalog generation changed: "
                        f"expected={args.expected_generation} "
                        f"actual={pointer['generation']}"
                    )
                candidate, candidate_source, candidate_sha = \
                    catalog_tool.load_catalog(
                        args.catalog, args.expected_catalog_sha256
                    )
                catalog_tool_entries = state_tool.load_ready_entries(candidate)
                if not catalog_tool_entries:
                    raise ValueError("Adapter Catalog candidate is empty")
                if (candidate["catalogId"] != source["catalogId"]
                        or candidate["generation"] <= source["catalogGeneration"]):
                    raise ValueError("Adapter Catalog candidate is not an upgrade")
                directory = transaction_directory(root, args.transaction_id)
                directory.mkdir(parents=True, exist_ok=True)
                content = candidate_source.read_bytes()
                if package_tool.sha256_bytes(content) != candidate_sha:
                    raise ValueError("Adapter Catalog candidate changed during staging")
                state_tool.exclusive_bytes(
                    candidate_path(root, args.transaction_id), content
                )
                now = registry_tool.utc_time(None)
                journal = {
                    "schemaVersion": 1, "product": JOURNAL_PRODUCT,
                    "transactionId": args.transaction_id,
                    "reconcilerId": config["reconcilerId"],
                    "configSha256": config_sha, "catalogId": source["catalogId"],
                    "sourceActivationGeneration": pointer["generation"],
                    "sourceCatalogGeneration": source["catalogGeneration"],
                    "sourceCatalogSha256": source["catalogSha256"],
                    "candidateCatalogGeneration": candidate["generation"],
                    "candidateCatalogSha256": candidate_sha,
                    "actor": args.actor, "reason": args.reason,
                    "status": "preparing", "switchedGeneration": None,
                    "rollbackGeneration": None, "healthAttempt": 0,
                    "lastOperation": None, "errorCode": None,
                    "createdAt": now, "updatedAt": now, "journalSha256": "0" * 64,
                }
                write_journal(path, journal)
            candidate, _, _ = catalog_tool.load_catalog(
                candidate_path(root, args.transaction_id),
                journal["candidateCatalogSha256"],
            )
            state_tool.load_ready_entries(candidate)
            drive(config, state_dir, root, path, journal)
            report = report_for(journal, capability_sha)
            if args.report:
                package_tool.write_json(Path(args.report).resolve(), report)
        passed = journal["status"] == "committed"
        marker = "PASS" if passed else "ERROR"
        print(
            f"PDR_ADAPTER_CATALOG_RECONCILE_{marker} "
            f"transaction={journal['transactionId']} status={journal['status']}"
        )
        return 0 if passed else 2
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_RECONCILE_ERROR: {error}", file=sys.stderr)
        return 2


def recover_command(args: argparse.Namespace) -> int:
    try:
        config, _, config_sha = load_config(
            args.config, args.expected_config_sha256
        )
        capability_sha = negotiate(config)
        root = transaction_root(args.transaction_dir)
        state_dir = state_tool.state_root(args.state_dir)
        path = journal_path(root, args.transaction_id)
        with ReconcileLease(root, args.transaction_id):
            journal = load_journal(path)
            if (journal["configSha256"] != config_sha
                    or journal["reconcilerId"] != config["reconcilerId"]):
                raise ValueError("Reconciler recovery config identity changed")
            candidate, _, _ = catalog_tool.load_catalog(
                candidate_path(root, args.transaction_id),
                journal["candidateCatalogSha256"],
            )
            state_tool.load_ready_entries(candidate)
            drive(config, state_dir, root, path, journal)
            report = report_for(journal, capability_sha)
            if args.report:
                package_tool.write_json(Path(args.report).resolve(), report)
        passed = journal["status"] == "committed"
        marker = "PASS" if passed else "ERROR"
        print(
            f"PDR_ADAPTER_CATALOG_RECONCILE_RECOVER_{marker} "
            f"transaction={journal['transactionId']} status={journal['status']}"
        )
        return 0 if passed else 2
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_RECONCILE_RECOVER_ERROR: {error}", file=sys.stderr)
        return 2


def revert_command(args: argparse.Namespace) -> int:
    try:
        config, _, config_sha = load_config(
            args.config, args.expected_config_sha256
        )
        capability_sha = negotiate(config)
        root = transaction_root(args.transaction_dir)
        state_dir = state_tool.state_root(args.state_dir)
        path = journal_path(root, args.transaction_id)
        with ReconcileLease(root, args.transaction_id):
            journal = load_journal(path)
            if (journal["configSha256"] != config_sha
                    or journal["reconcilerId"] != config["reconcilerId"]):
                raise ValueError("Reconciler revert config identity changed")
            if journal["status"] == "committed":
                automatic_rollback(
                    config, state_dir, root, path, journal,
                    "explicit-revert-requested",
                )
            elif journal["status"] in {
                    "rolling-back", "catalog-rolled-back", "rollback-hook",
                    "rollback-failed"}:
                resume_rollback(config, state_dir, root, path, journal)
            elif journal["status"] != "rolled-back":
                raise ValueError(
                    "only a committed or interrupted rollback transaction "
                    "can be reverted"
                )
            report = report_for(journal, capability_sha)
            if args.report:
                package_tool.write_json(Path(args.report).resolve(), report)
        succeeded = journal["status"] == "rolled-back"
        marker = "PASS" if succeeded else "ERROR"
        print(
            f"PDR_ADAPTER_CATALOG_RECONCILE_REVERT_{marker} "
            f"transaction={journal['transactionId']} status={journal['status']}"
        )
        return 0 if succeeded else 2
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_RECONCILE_REVERT_ERROR: {error}", file=sys.stderr)
        return 2


def status_command(args: argparse.Namespace) -> int:
    try:
        root = transaction_root(args.transaction_dir)
        journal = load_journal(journal_path(root, args.transaction_id))
        report = {
            "schemaVersion": 1, "product": STATUS_PRODUCT,
            "transactionId": journal["transactionId"],
            "reconcilerId": journal["reconcilerId"],
            "catalogId": journal["catalogId"], "status": journal["status"],
            "terminal": journal["status"] in TERMINAL_STATUSES,
            "sourceActivationGeneration": journal["sourceActivationGeneration"],
            "candidateCatalogGeneration": journal["candidateCatalogGeneration"],
            "switchedGeneration": journal["switchedGeneration"],
            "rollbackGeneration": journal["rollbackGeneration"],
            "healthAttempts": journal["healthAttempt"],
            "errorCode": journal["errorCode"],
            "journalSha256": journal["journalSha256"],
            "observedAt": registry_tool.utc_time(None),
        }
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print(
            "PDR_ADAPTER_CATALOG_RECONCILE_STATUS_PASS "
            f"transaction={journal['transactionId']} status={journal['status']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_RECONCILE_STATUS_ERROR: {error}", file=sys.stderr)
        return 2


def add_common(command: argparse.ArgumentParser) -> None:
    command.add_argument("--config", required=True)
    command.add_argument("--expected-config-sha256", required=True)
    command.add_argument("--state-dir", required=True)
    command.add_argument("--transaction-dir", required=True)
    command.add_argument("--transaction-id", required=True)
    command.add_argument("--report")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    run = commands.add_parser("run")
    add_common(run)
    run.add_argument("--catalog", required=True)
    run.add_argument("--expected-catalog-sha256", required=True)
    run.add_argument("--expected-generation", type=int, required=True)
    run.add_argument("--actor", required=True)
    run.add_argument("--reason", required=True)
    run.set_defaults(handler=run_command)
    recover = commands.add_parser("recover")
    add_common(recover)
    recover.set_defaults(handler=recover_command)
    revert = commands.add_parser("revert")
    add_common(revert)
    revert.set_defaults(handler=revert_command)
    status = commands.add_parser("status")
    status.add_argument("--transaction-dir", required=True)
    status.add_argument("--transaction-id", required=True)
    status.add_argument("--report")
    status.set_defaults(handler=status_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
