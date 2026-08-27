#!/usr/bin/env python3
"""File-backed idempotent reference Control Authorizer for Fleet tests."""

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
    "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerCapabilityRequest"
CAPABILITY_MANIFEST = \
    "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerCapabilityManifest"
REQUEST = "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerRequest"
RESPONSE = "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerResponse"
CAPABILITIES = [
    "deny-by-default", "idempotent-control-authorization",
    "no-secret-evidence", "principal-binding", "sanitized-control-intent",
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
    value = os.environ.get("PDR_CONTROL_AUTHORIZER_STATE_ROOT")
    if not value or not Path(value).is_absolute():
        raise ValueError("Control Authorizer state root is unavailable")
    supplied = Path(value)
    if supplied.is_symlink() or bool(
            getattr(supplied, "is_junction", lambda: False)()):
        raise ValueError("Control Authorizer state root is unsafe")
    root = supplied.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_request(request: Any) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "authorizerId",
        "authorizationId", "rolloutId", "operationId", "action",
        "claimedActor", "reasonSha256", "expectedControlGeneration",
        "waveId", "waveIndex", "catalogId", "candidateCatalogGeneration",
        "candidateCatalogSha256", "gateEvidenceSha256",
    }
    if (not isinstance(request, dict) or set(request) != fields
            or request.get("schemaVersion") != 1
            or request.get("product") != REQUEST
            or any(IDENTIFIER.fullmatch(str(request.get(name, ""))) is None
                   for name in (
                       "authorizerId", "authorizationId", "rolloutId",
                       "operationId", "claimedActor", "waveId", "catalogId"))
            or request.get("action") not in {"resume", "abort"}
            or SHA256.fullmatch(str(request.get("reasonSha256", ""))) is None
            or type(request.get("expectedControlGeneration")) is not int
            or request["expectedControlGeneration"] < 0
            or type(request.get("waveIndex")) is not int
            or not 0 <= request["waveIndex"] < 32
            or type(request.get("candidateCatalogGeneration")) is not int
            or request["candidateCatalogGeneration"] < 2
            or SHA256.fullmatch(
                str(request.get("candidateCatalogSha256", ""))) is None
            or (request.get("gateEvidenceSha256") is not None
                and SHA256.fullmatch(
                    str(request["gateEvidenceSha256"])) is None)):
        raise ValueError("Control Authorizer request is malformed")


def response_for(request: dict[str, Any], decision: str,
                 principal: str | None) -> dict[str, Any]:
    evidence = hashlib.sha256(json.dumps({
        "authorizationId": request["authorizationId"],
        "action": request["action"], "claimedActor": request["claimedActor"],
        "reasonSha256": request["reasonSha256"], "decision": decision,
        "principalId": principal,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schemaVersion": 1, "product": RESPONSE,
        "requestId": request["requestId"],
        "authorizerId": request["authorizerId"],
        "authorizationId": request["authorizationId"],
        "rolloutId": request["rolloutId"],
        "operationId": request["operationId"], "action": request["action"],
        "allowed": decision == "allow", "decision": decision,
        "principalId": principal, "evidenceSha256": evidence,
        "diagnosticCode": None if decision == "allow" else "policy-denied",
    }


def response_gate() -> None:
    value = os.environ.get("PDR_CONTROL_AUTHORIZER_RESPONSE_GATE")
    if not value:
        return
    base = Path(value)
    Path(str(base) + ".started").write_text("started", encoding="utf-8")
    deadline = time.monotonic() + 25
    while not Path(str(base) + ".release").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("Control Authorizer response gate timed out")
        time.sleep(0.02)


def authorize(request: dict[str, Any]) -> dict[str, Any]:
    validate_request(request)
    root = state_root()
    path = root / f"{request['authorizationId']}.json"
    identity = {
        "authorizerId": request["authorizerId"],
        "rolloutId": request["rolloutId"],
        "operationId": request["operationId"], "action": request["action"],
        "claimedActor": request["claimedActor"],
        "reasonSha256": request["reasonSha256"],
        "expectedControlGeneration": request["expectedControlGeneration"],
    }
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError("Control authorization state is unsafe")
        stored = json.loads(path.read_bytes())
        if stored.get("identity") != identity:
            raise ValueError("Control authorization identity changed")
        response = dict(stored["response"])
        response["requestId"] = request["requestId"]
        return response
    decision = os.environ.get("PDR_CONTROL_AUTHORIZER_DECISION", "deny")
    if decision not in {"allow", "deny"}:
        raise ValueError("Control authorization decision is malformed")
    principal = os.environ.get("PDR_CONTROL_AUTHORIZER_PRINCIPAL")
    if decision == "allow":
        if IDENTIFIER.fullmatch(str(principal or "")) is None:
            raise ValueError("authorized principal is unavailable")
    elif principal and IDENTIFIER.fullmatch(principal) is None:
        raise ValueError("denied principal is malformed")
    secret = os.environ.get("PDR_CONTROL_AUTHORIZER_SECRET_SENTINEL")
    if secret:
        print(secret, file=sys.stderr)
    response = response_for(request, decision, principal)
    atomic_json(path, {"identity": identity, "response": response})
    response_gate()
    return response


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        if isinstance(request, dict) and request.get("product") == CAPABILITY_REQUEST:
            if (set(request) != {
                    "schemaVersion", "product", "requestId", "authorizerId"
                } or request.get("schemaVersion") != 1
                    or IDENTIFIER.fullmatch(
                        str(request.get("authorizerId", ""))) is None):
                raise ValueError("Control Authorizer capability request is malformed")
            response = {
                "schemaVersion": 1, "product": CAPABILITY_MANIFEST,
                "requestId": request["requestId"],
                "authorizerId": request["authorizerId"],
                "implementationId": "file-control-authorizer-v1",
                "protocolMajor": 1, "protocolMinor": 0,
                "capabilities": CAPABILITIES,
            }
        else:
            response = authorize(request)
        print(json.dumps(response, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_CONTROL_AUTHORIZER_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
