#!/usr/bin/env python3
"""Reference Fleet Node Executor backed by the real Catalog Reconciler."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterator


CAPABILITY_REQUEST = "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorCapabilityRequest"
CAPABILITY_MANIFEST = "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorCapabilityManifest"
REQUEST = "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorRequest"
RESPONSE = "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorResponse"
NODE_MAP = "PocoDDSRuntimeTeamContractAdapterCatalogFleetNodeMap"
CAPABILITIES = [
    "idempotent-node-deploy", "node-reconcile-status",
    "reverse-order-revert", "wave-rollout",
]
PATH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def absolute_path(value: Any, label: str, *, file: bool = False) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError(f"{label} must be absolute")
    supplied = Path(value)
    if supplied.is_symlink() or bool(
            getattr(supplied, "is_junction", lambda: False)()):
        raise ValueError(f"{label} must not be a link")
    result = supplied.resolve()
    if file and not result.is_file():
        raise ValueError(f"{label} is unavailable")
    return result


def load_mapping(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_bytes())
    if (not isinstance(document, dict) or set(document) != {
            "schemaVersion", "product", "executorId", "auditPath", "nodes"
        } or document.get("schemaVersion") != 1
            or document.get("product") != NODE_MAP
            or IDENTIFIER.fullmatch(str(document.get("executorId", ""))) is None
            or not isinstance(document.get("nodes"), list)
            or not 1 <= len(document["nodes"]) <= 1024):
        raise ValueError("Fleet node map is malformed")
    absolute_path(document["auditPath"], "Fleet audit path")
    seen: set[str] = set()
    for node in document["nodes"]:
        if (not isinstance(node, dict) or set(node) != {
                "nodeId", "stateDir", "transactionDir", "lifecycleStateDir",
                "reconcilerConfigPath", "reconcilerConfigSha256",
                "catalogPath", "catalogSha256",
                "expectedActivationGeneration", "healthMode",
            } or PATH_ID.fullmatch(str(node.get("nodeId", ""))) is None
                or node["nodeId"] in seen
                or type(node.get("expectedActivationGeneration")) is not int
                or node["expectedActivationGeneration"] < 1
                or node.get("healthMode") not in {"healthy", "unhealthy"}
                or any(SHA256.fullmatch(str(node.get(name, ""))) is None
                       for name in (
                           "reconcilerConfigSha256", "catalogSha256"))):
            raise ValueError("Fleet node mapping is malformed")
        for name in ("stateDir", "transactionDir", "lifecycleStateDir"):
            absolute_path(node[name], f"Fleet node {name}")
        for path_name, sha_name in (
                ("reconcilerConfigPath", "reconcilerConfigSha256"),
                ("catalogPath", "catalogSha256")):
            pinned = absolute_path(node[path_name], f"Fleet node {path_name}", file=True)
            if digest(pinned) != node[sha_name]:
                raise ValueError(f"Fleet node {path_name} pin changed")
        seen.add(node["nodeId"])
    if document["nodes"] != sorted(document["nodes"], key=lambda item: item["nodeId"]):
        raise ValueError("Fleet node mappings are not sorted")
    return document


def validate_request(request: Any, executor_id: str) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "executorId", "rolloutId",
        "nodeId", "operation", "catalogId", "candidateCatalogGeneration",
        "candidateCatalogSha256", "expectedActivationGeneration",
    }
    if (not isinstance(request, dict) or set(request) != fields
            or request.get("schemaVersion") != 1
            or request.get("product") != REQUEST
            or request.get("executorId") != executor_id
            or PATH_ID.fullmatch(str(request.get("rolloutId", ""))) is None
            or PATH_ID.fullmatch(str(request.get("nodeId", ""))) is None
            or request.get("operation") not in {"deploy", "revert", "status"}
            or IDENTIFIER.fullmatch(str(request.get("catalogId", ""))) is None
            or type(request.get("candidateCatalogGeneration")) is not int
            or request["candidateCatalogGeneration"] < 2
            or SHA256.fullmatch(
                str(request.get("candidateCatalogSha256", ""))) is None
            or type(request.get("expectedActivationGeneration")) is not int
            or request["expectedActivationGeneration"] < 1):
        raise ValueError("Fleet Executor request is malformed")


@contextlib.contextmanager
def reconciler_environment(node: dict[str, Any]) -> Iterator[None]:
    names = {
        "PDR_RECONCILER_STATE_ROOT": node["lifecycleStateDir"],
        "PDR_RECONCILER_HEALTH_MODE": node["healthMode"],
    }
    sentinel = os.environ.get("PDR_FLEET_EXECUTOR_SECRET_SENTINEL")
    if sentinel:
        names["PDR_RECONCILER_SECRET_SENTINEL"] = sentinel
    previous = {name: os.environ.get(name) for name in names}
    try:
        os.environ.update(names)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def capture(function: Any, args: argparse.Namespace) -> int:
    with io.StringIO() as stdout, io.StringIO() as stderr, \
            contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        return function(args)


def current_generation(state_tool: Any, node: dict[str, Any]) -> int:
    root = state_tool.state_root(node["stateDir"])
    pointer, _, _, _, _ = state_tool.current_context(root)
    return pointer["generation"]


def report_path(node: dict[str, Any], transaction_id: str,
                operation: str) -> Path:
    return Path(node["transactionDir"]).resolve() / "fleet-reports" / \
        f"{transaction_id}.{operation}.json"


def audit(mapping: dict[str, Any], operation: str, node_id: str,
          rollout_id: str) -> None:
    path = Path(mapping["auditPath"]).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{operation} {node_id} {rollout_id}\n".encode()
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, line)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def gate_after_side_effect(node_id: str) -> None:
    if os.environ.get("PDR_FLEET_EXECUTOR_GATE_NODE") != node_id:
        return
    value = os.environ.get("PDR_FLEET_EXECUTOR_GATE")
    if not value:
        return
    base = Path(value)
    Path(str(base) + ".started").write_text("started", encoding="utf-8")
    deadline = time.monotonic() + 25
    while not Path(str(base) + ".release").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("Fleet Executor response gate timed out")
        time.sleep(0.02)


def execute(mapping: dict[str, Any], request: dict[str, Any],
            reconciler: Any, state_tool: Any) -> dict[str, Any]:
    validate_request(request, mapping["executorId"])
    by_id = {item["nodeId"]: item for item in mapping["nodes"]}
    node = by_id.get(request["nodeId"])
    if node is None:
        raise ValueError("Fleet node is not mapped")
    if (node["catalogSha256"] != request["candidateCatalogSha256"]
            or node["expectedActivationGeneration"]
                != request["expectedActivationGeneration"]):
        raise ValueError("Fleet node candidate identity changed")
    transaction_id = f"{request['rolloutId']}.{request['nodeId']}"
    output = report_path(node, transaction_id, request["operation"])
    output.parent.mkdir(parents=True, exist_ok=True)
    common = {
        "config": node["reconcilerConfigPath"],
        "expected_config_sha256": node["reconcilerConfigSha256"],
        "state_dir": node["stateDir"],
        "transaction_dir": node["transactionDir"],
        "transaction_id": transaction_id, "report": str(output),
    }
    with reconciler_environment(node):
        if request["operation"] == "deploy":
            args = argparse.Namespace(
                **common, catalog=node["catalogPath"],
                expected_catalog_sha256=node["catalogSha256"],
                expected_generation=node["expectedActivationGeneration"],
                actor=mapping["executorId"],
                reason=f"fleet rollout {request['rolloutId']} node {request['nodeId']}",
            )
            code = capture(reconciler.run_command, args)
        elif request["operation"] == "revert":
            code = capture(reconciler.revert_command, argparse.Namespace(**common))
        else:
            code = capture(reconciler.status_command, argparse.Namespace(
                transaction_dir=node["transactionDir"],
                transaction_id=transaction_id, report=str(output),
            ))
    report = json.loads(output.read_bytes()) if output.is_file() else {}
    report_sha = digest(output) if output.is_file() else None
    operation = request["operation"]
    expected_status = "committed" if operation == "deploy" else "rolled-back"
    accepted = code == 0 and report.get("status") == expected_status
    if operation == "status":
        accepted = code == 0
    state = report.get("status", "unknown")
    if operation == "deploy" and not accepted:
        state = "failed"
    elif operation == "revert" and not accepted:
        state = "failed"
    elif state not in {"committed", "rolled-back", "failed", "unknown"}:
        state = "unknown"
    diagnostic = None if accepted else report.get("errorCode") or \
        f"node-{operation}-failed"
    audit(mapping, operation, request["nodeId"], request["rolloutId"])
    gate_after_side_effect(request["nodeId"])
    return {
        "schemaVersion": 1, "product": RESPONSE,
        "requestId": request["requestId"], "executorId": request["executorId"],
        "rolloutId": request["rolloutId"], "nodeId": request["nodeId"],
        "operation": operation, "accepted": accepted, "state": state,
        "currentActivationGeneration": current_generation(state_tool, node),
        "reconcileReportSha256": report_sha,
        "diagnosticCode": diagnostic,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--mapping", required=True)
    result.add_argument("--tools-dir", required=True)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        mapping_path = absolute_path(args.mapping, "Fleet node map", file=True)
        tools_dir = absolute_path(args.tools_dir, "Fleet tools directory")
        if not tools_dir.is_dir():
            raise ValueError("Fleet tools directory is unavailable")
        sys.path.insert(0, str(tools_dir))
        import team_contract_adapter_catalog_reconciler as reconciler
        import team_contract_adapter_catalog_state as state_tool
        mapping = load_mapping(mapping_path)
        request = json.loads(sys.stdin.read())
        if isinstance(request, dict) and request.get("product") == CAPABILITY_REQUEST:
            if (set(request) != {
                    "schemaVersion", "product", "requestId", "executorId"
                } or request.get("schemaVersion") != 1
                    or request.get("executorId") != mapping["executorId"]):
                raise ValueError("Fleet capability request is malformed")
            response = {
                "schemaVersion": 1, "product": CAPABILITY_MANIFEST,
                "requestId": request["requestId"],
                "executorId": request["executorId"],
                "implementationId": "reconciler-fleet-node-executor-v1",
                "protocolMajor": 1, "protocolMinor": 0,
                "capabilities": CAPABILITIES,
            }
        else:
            response = execute(mapping, request, reconciler, state_tool)
        print(json.dumps(response, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_FLEET_NODE_EXECUTOR_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
