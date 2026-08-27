#!/usr/bin/env python3
"""File-backed reference lifecycle hook for Adapter Catalog reconciliation."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any


CAPABILITY_REQUEST = "PocoDDSRuntimeTeamContractAdapterCatalogReconcilerCapabilityRequest"
CAPABILITY_MANIFEST = "PocoDDSRuntimeTeamContractAdapterCatalogReconcilerCapabilityManifest"
REQUEST = "PocoDDSRuntimeTeamContractAdapterCatalogReconcilerRequest"
RESPONSE = "PocoDDSRuntimeTeamContractAdapterCatalogReconcilerResponse"
CAPABILITIES = [
    "abort", "activate", "bounded-drain", "commit", "health-gate",
    "idempotent-operations", "prepare", "rollback",
]
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
OPERATIONS = {"prepare", "drain", "activate", "health", "commit", "abort", "rollback"}
RANK = {None: 0, "prepared": 1, "drained": 2, "activated": 3,
        "healthy": 4, "committed": 5}


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        content = (
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        descriptor = os.open(
            temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def state_root() -> Path:
    value = os.environ.get("PDR_RECONCILER_STATE_ROOT")
    if not value:
        raise ValueError("PDR_RECONCILER_STATE_ROOT is unavailable")
    root = Path(value)
    if not root.is_absolute() or root.is_symlink():
        raise ValueError("reconciler state root is unsafe")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("reconciler state root is unavailable")
    return root


def validate_request(request: Any) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "transactionId",
        "reconcilerId", "operation", "catalogId",
        "sourceActivationGeneration", "sourceCatalogGeneration",
        "sourceCatalogSha256", "candidateCatalogGeneration",
        "candidateCatalogSha256", "currentActivationGeneration", "attempt",
    }
    if (not isinstance(request, dict) or set(request) != fields
            or request.get("schemaVersion") != 1
            or request.get("product") != REQUEST
            or any(IDENTIFIER.fullmatch(str(request.get(name, ""))) is None
                   for name in ("transactionId", "reconcilerId", "catalogId"))
            or request.get("operation") not in OPERATIONS
            or any(type(request.get(name)) is not int or request[name] < 1
                   for name in (
                       "sourceActivationGeneration", "sourceCatalogGeneration",
                       "candidateCatalogGeneration", "currentActivationGeneration"))
            or type(request.get("attempt")) is not int or request["attempt"] < 0
            or any(SHA256.fullmatch(str(request.get(name, ""))) is None
                   for name in ("sourceCatalogSha256", "candidateCatalogSha256"))):
        raise ValueError("reconciler lifecycle request is malformed")


def load_state(path: Path, request: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return {
            "transactionId": request["transactionId"],
            "catalogId": request["catalogId"],
            "candidateCatalogSha256": request["candidateCatalogSha256"],
            "state": None,
        }
    if path.is_symlink() or not path.is_file():
        raise ValueError("reconciler lifecycle state is unsafe")
    document = json.loads(path.read_bytes())
    if (not isinstance(document, dict)
            or document.get("transactionId") != request["transactionId"]
            or document.get("catalogId") != request["catalogId"]
            or document.get("candidateCatalogSha256")
                != request["candidateCatalogSha256"]
            or document.get("state") not in {
                None, "prepared", "drained", "activated", "healthy",
                "committed", "aborted", "rolled-back",
            }):
        raise ValueError("reconciler lifecycle state identity changed")
    return document


def gate_health() -> None:
    gate = os.environ.get("PDR_RECONCILER_HEALTH_GATE")
    if not gate:
        return
    base = Path(gate)
    Path(str(base) + ".started").write_text("started", encoding="utf-8")
    deadline = time.monotonic() + 20
    while not Path(str(base) + ".release").exists():
        if time.monotonic() > deadline:
            raise RuntimeError("health gate timeout")
        time.sleep(0.02)


def respond(request: dict[str, Any], accepted: bool, state: str,
            diagnostic: str | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": RESPONSE,
        "requestId": request["requestId"],
        "transactionId": request["transactionId"],
        "reconcilerId": request["reconcilerId"],
        "operation": request["operation"], "accepted": accepted,
        "state": state, "pendingOperations": 0,
        "diagnosticCode": diagnostic,
    }


def execute(request: dict[str, Any]) -> dict[str, Any]:
    validate_request(request)
    root = state_root()
    path = root / f"{request['transactionId']}.json"
    state = load_state(path, request)
    current = state["state"]
    operation = request["operation"]
    rejected = os.environ.get("PDR_RECONCILER_REJECT_OPERATION")
    if rejected == operation:
        return respond(
            request, False, current or "unprepared",
            f"{operation}-injected-rejection",
        )
    if operation == "health":
        gate_health()
        secret = os.environ.get("PDR_RECONCILER_SECRET_SENTINEL")
        if secret:
            print(secret, file=sys.stderr)
        if os.environ.get("PDR_RECONCILER_HEALTH_MODE", "healthy") == "unhealthy":
            return respond(request, False, "unhealthy", "health-gate-rejected")
        if current not in {"activated", "healthy", "committed"}:
            return respond(request, False, "unhealthy", "not-activated")
        if current != "committed":
            state["state"] = "healthy"
            atomic_json(path, state)
        return respond(request, True, "healthy")
    target = {
        "prepare": "prepared", "drain": "drained", "activate": "activated",
        "commit": "committed", "abort": "aborted", "rollback": "rolled-back",
    }[operation]
    if current == target:
        return respond(request, True, target)
    if operation == "abort":
        if current in {None, "prepared", "drained", "aborted"}:
            state["state"] = "aborted"
            atomic_json(path, state)
            return respond(request, True, "aborted")
        return respond(request, False, current or "unprepared", "abort-too-late")
    if operation == "rollback":
        if current in {"activated", "healthy", "committed", "rolled-back"}:
            state["state"] = "rolled-back"
            atomic_json(path, state)
            return respond(request, True, "rolled-back")
        return respond(request, False, current or "unprepared", "rollback-too-early")
    prerequisite = {"prepare": None, "drain": "prepared", "activate": "drained",
                    "commit": "healthy"}[operation]
    if current != prerequisite and not (
            current in RANK and prerequisite in RANK
            and RANK[current] >= RANK[prerequisite]
            and RANK[current] >= RANK[target]):
        return respond(request, False, current or "unprepared", "phase-order-rejected")
    state["state"] = target
    atomic_json(path, state)
    return respond(request, True, target)


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        if (isinstance(request, dict)
                and request.get("product") == CAPABILITY_REQUEST):
            if (set(request) != {
                    "schemaVersion", "product", "requestId", "reconcilerId"
                } or request.get("schemaVersion") != 1
                    or IDENTIFIER.fullmatch(
                        str(request.get("reconcilerId", ""))) is None):
                raise ValueError("reconciler capability request is malformed")
            response = {
                "schemaVersion": 1, "product": CAPABILITY_MANIFEST,
                "requestId": request["requestId"],
                "reconcilerId": request["reconcilerId"],
                "implementationId": "file-lifecycle-reconciler-v1",
                "protocolMajor": 1, "protocolMinor": 0,
                "capabilities": CAPABILITIES,
            }
        else:
            response = execute(request)
        print(json.dumps(response, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_LIFECYCLE_RECONCILER_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
