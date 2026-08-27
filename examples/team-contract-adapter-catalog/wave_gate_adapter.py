#!/usr/bin/env python3
"""File-backed idempotent reference Wave Gate for Fleet rollout tests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any


CAPABILITY_REQUEST = \
    "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateCapabilityRequest"
CAPABILITY_MANIFEST = \
    "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateCapabilityManifest"
REQUEST = "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateRequest"
RESPONSE = "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateResponse"
CAPABILITIES = [
    "bounded-observation", "idempotent-evaluation", "no-secret-evidence",
    "wave-slo-gate",
]
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        content = (json.dumps(document, sort_keys=True, separators=(",", ":"))
                   + "\n").encode()
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
    value = os.environ.get("PDR_WAVE_GATE_STATE_ROOT")
    if not value or not Path(value).is_absolute():
        raise ValueError("Wave Gate state root is unavailable")
    supplied = Path(value)
    if supplied.is_symlink() or bool(
            getattr(supplied, "is_junction", lambda: False)()):
        raise ValueError("Wave Gate state root is unsafe")
    root = supplied.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_request(request: Any) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "gateId", "evaluationId",
        "rolloutId", "waveId", "waveIndex", "catalogId",
        "candidateCatalogGeneration", "candidateCatalogSha256", "attempt",
        "observationStartedAt", "nodeCounts",
    }
    counts = request.get("nodeCounts") if isinstance(request, dict) else None
    if (not isinstance(request, dict) or set(request) != fields
            or request.get("schemaVersion") != 1
            or request.get("product") != REQUEST
            or any(IDENTIFIER.fullmatch(str(request.get(name, ""))) is None
                   for name in (
                       "gateId", "evaluationId", "rolloutId", "waveId",
                       "catalogId"))
            or type(request.get("waveIndex")) is not int
            or not 0 <= request["waveIndex"] < 32
            or type(request.get("candidateCatalogGeneration")) is not int
            or request["candidateCatalogGeneration"] < 2
            or SHA256.fullmatch(
                str(request.get("candidateCatalogSha256", ""))) is None
            or type(request.get("attempt")) is not int
            or not 1 <= request["attempt"] <= 100
            or not isinstance(request.get("observationStartedAt"), str)
            or not isinstance(counts, dict)
            or set(counts) != {"pending", "committed", "failed", "rolled-back"}
            or any(type(value) is not int or value < 0
                   for value in counts.values())):
        raise ValueError("Wave Gate request is malformed")


def response_for(request: dict[str, Any], decision: str) -> dict[str, Any]:
    evidence = hashlib.sha256(json.dumps({
        "rolloutId": request["rolloutId"], "waveId": request["waveId"],
        "attempt": request["attempt"], "nodeCounts": request["nodeCounts"],
        "decision": decision,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    diagnostic = {
        "pass": None, "pause": "slo-observation-paused",
        "fail": "slo-threshold-failed",
    }[decision]
    return {
        "schemaVersion": 1, "product": RESPONSE,
        "requestId": request["requestId"], "gateId": request["gateId"],
        "evaluationId": request["evaluationId"],
        "rolloutId": request["rolloutId"], "waveId": request["waveId"],
        "attempt": request["attempt"], "accepted": decision == "pass",
        "decision": decision, "evidenceSha256": evidence,
        "diagnosticCode": diagnostic,
    }


def gate_response() -> None:
    value = os.environ.get("PDR_WAVE_GATE_RESPONSE_GATE")
    if not value:
        return
    base = Path(value)
    Path(str(base) + ".started").write_text("started", encoding="utf-8")
    deadline = time.monotonic() + 25
    while not Path(str(base) + ".release").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("Wave Gate response gate timed out")
        time.sleep(0.02)


def evaluate(request: dict[str, Any]) -> dict[str, Any]:
    validate_request(request)
    root = state_root()
    path = root / f"{request['evaluationId']}.json"
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError("Wave Gate evaluation state is unsafe")
        stored = json.loads(path.read_bytes())
        identity = stored.get("identity", {})
        if identity != {
                "gateId": request["gateId"], "rolloutId": request["rolloutId"],
                "waveId": request["waveId"], "attempt": request["attempt"],
                "candidateCatalogSha256": request["candidateCatalogSha256"],
            }:
            raise ValueError("Wave Gate evaluation identity changed")
        response = dict(stored["response"])
        response["requestId"] = request["requestId"]
        return response
    decision = os.environ.get("PDR_WAVE_GATE_DECISION", "pass")
    if decision not in {"pass", "pause", "fail"}:
        raise ValueError("Wave Gate decision is malformed")
    secret = os.environ.get("PDR_WAVE_GATE_SECRET_SENTINEL")
    if secret:
        print(secret, file=sys.stderr)
    response = response_for(request, decision)
    atomic_json(path, {
        "identity": {
            "gateId": request["gateId"], "rolloutId": request["rolloutId"],
            "waveId": request["waveId"], "attempt": request["attempt"],
            "candidateCatalogSha256": request["candidateCatalogSha256"],
        },
        "response": response,
    })
    gate_response()
    return response


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        if isinstance(request, dict) and request.get("product") == CAPABILITY_REQUEST:
            if (set(request) != {
                    "schemaVersion", "product", "requestId", "gateId"
                } or request.get("schemaVersion") != 1
                    or IDENTIFIER.fullmatch(
                        str(request.get("gateId", ""))) is None):
                raise ValueError("Wave Gate capability request is malformed")
            response = {
                "schemaVersion": 1, "product": CAPABILITY_MANIFEST,
                "requestId": request["requestId"], "gateId": request["gateId"],
                "implementationId": "file-wave-gate-v1",
                "protocolMajor": 1, "protocolMinor": 0,
                "capabilities": CAPABILITIES,
            }
        else:
            response = evaluate(request)
        print(json.dumps(response, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_WAVE_GATE_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
