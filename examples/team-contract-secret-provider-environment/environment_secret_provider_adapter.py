#!/usr/bin/env python3
"""Reference Secret Provider with leased dual-version environment rotation."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


MAPPING_PRODUCT = "PocoDDSRuntimeTeamContractSecretProviderEnvironmentMapping"
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractSecretProviderRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractSecretProviderResponse"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractSecretProviderCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractSecretProviderCapabilityManifest"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITIES = [
    "bounded-secret", "leased-secret", "no-secret-persistence",
    "revocation-aware", "rotation-fallback", "scoped-read",
    "version-pinned-read",
]


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("rotation deadline must include a timezone")
    return result.astimezone(timezone.utc)


def load_mapping(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("secret mapping path must be absolute")
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError("secret mapping must be a regular non-link file")
    document = json.loads(path.read_bytes())
    if (not isinstance(document, dict)
            or set(document) != {
                "schemaVersion", "product", "providerId", "entries"
            }
            or document.get("schemaVersion") not in {1, 2}
            or document.get("product") != MAPPING_PRODUCT
            or not IDENTIFIER.fullmatch(str(document.get("providerId", "")))
            or not isinstance(document.get("entries"), list)
            or not document["entries"] or len(document["entries"]) > 128):
        raise ValueError("secret mapping is malformed")
    seen: set[tuple[str, str]] = set()
    for entry in document["entries"]:
        fields = {"secretId", "version", "environmentVariable"} \
            | ({"status"} if document["schemaVersion"] == 2 else set())
        if (not isinstance(entry, dict) or set(entry) != fields
                or any(not IDENTIFIER.fullmatch(str(entry.get(name, "")))
                       for name in ("secretId", "version"))
                or not ENVIRONMENT_NAME.fullmatch(
                    str(entry.get("environmentVariable", "")))
                or (document["schemaVersion"] == 2
                    and entry.get("status") not in {"active", "revoked"})
                or (entry["secretId"], entry["version"]) in seen):
            raise ValueError("secret mapping entry is malformed or duplicated")
        seen.add((entry["secretId"], entry["version"]))
    return document


def read_request() -> dict[str, Any]:
    content = sys.stdin.buffer.read(1024 * 1024 + 1)
    if not content or len(content) > 1024 * 1024:
        raise ValueError("secret request size is outside policy")
    document = json.loads(content)
    if not isinstance(document, dict):
        raise ValueError("secret request is malformed")
    return document


def requested_versions(reference: dict[str, Any], leased: bool) \
        -> tuple[list[str], datetime | None]:
    if reference.get("kind") == "secret-ref":
        if (set(reference) != {"kind", "providerId", "secretId", "version"}
                or not IDENTIFIER.fullmatch(str(reference.get("version", "")))):
            raise ValueError("secret provider reference is malformed")
        return [reference["version"]], None
    versions = reference.get("versions")
    if (reference.get("kind") != "secret-rotation-ref" or not leased
            or set(reference) != {
                "kind", "providerId", "secretId", "versions", "fallbackUntil"
            }
            or not isinstance(versions, list)
            or not 2 <= len(versions) <= 4
            or len(versions) != len(set(versions))
            or any(not IDENTIFIER.fullmatch(str(item)) for item in versions)
            or not isinstance(reference.get("fallbackUntil"), str)):
        raise ValueError("secret rotation reference is malformed")
    return list(versions), parse_time(reference["fallbackUntil"])


def execute(request: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    reference = request.get("reference")
    leased = request.get("schemaVersion") == 2
    fields = {
        "schemaVersion", "product", "requestId", "providerId",
        "operation", "reference",
    } | ({"requestedLeaseSeconds"} if leased else set())
    if (set(request) != fields
            or request.get("schemaVersion") not in {1, 2}
            or request.get("product") != REQUEST_PRODUCT
            or request.get("providerId") != mapping["providerId"]
            or request.get("operation") != ("lease" if leased else "resolve")
            or not IDENTIFIER.fullmatch(str(request.get("requestId", "")))
            or not isinstance(reference, dict)
            or reference.get("providerId") != mapping["providerId"]
            or not IDENTIFIER.fullmatch(str(reference.get("secretId", "")))
            or (leased and (type(request.get("requestedLeaseSeconds")) is not int
                or not 2 <= request["requestedLeaseSeconds"] <= 3600))):
        raise ValueError("secret provider request is malformed")
    versions, fallback_until = requested_versions(reference, leased)
    error: str | None = None
    value: str | None = None
    selected_version: str | None = None
    now = datetime.now(timezone.utc)
    for index, version in enumerate(versions):
        selected = next((
            entry for entry in mapping["entries"]
            if entry["secretId"] == reference["secretId"]
            and entry["version"] == version
        ), None)
        if selected is None or selected.get("status", "active") == "revoked":
            continue
        candidate = os.environ.get(selected["environmentVariable"])
        if not candidate or "\x00" in candidate:
            continue
        if index > 0 and fallback_until is not None and now > fallback_until:
            error = "secret rotation fallback window expired"
            break
        selected_version = version
        value = candidate
        break
    if value is None and error is None:
        error = "secret version is unavailable or revoked"
    result = {
        "schemaVersion": request["schemaVersion"], "product": RESPONSE_PRODUCT,
        "requestId": request["requestId"], "providerId": request["providerId"],
        "operation": request["operation"], "passed": error is None,
        "reference": reference,
        "secretBase64": base64.b64encode(value.encode()).decode()
            if value is not None else None,
        "error": error,
    }
    if leased:
        result.update({
            "selectedVersion": selected_version,
            "leaseId": request["requestId"] if value is not None else None,
            "issuedAt": now.isoformat() if value is not None else None,
            "expiresAt": (
                now + timedelta(seconds=request["requestedLeaseSeconds"])
            ).isoformat() if value is not None else None,
        })
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--mapping", required=True)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        mapping = load_mapping(args.mapping)
        request = read_request()
        if request.get("product") == CAPABILITY_REQUEST_PRODUCT:
            if (set(request) != {
                    "schemaVersion", "product", "requestId", "providerId"
                } or request.get("schemaVersion") != 1
                    or request.get("providerId") != mapping["providerId"]):
                raise ValueError("secret capability request is malformed")
            result = {
                "schemaVersion": 1, "product": CAPABILITY_MANIFEST_PRODUCT,
                "requestId": request["requestId"],
                "providerId": request["providerId"],
                "implementationId": "pdr-environment-secret-provider-v2",
                "protocolMajor": 1, "protocolMinor": 1,
                "capabilities": CAPABILITIES,
            }
        else:
            result = execute(request, mapping)
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_SECRET_PROVIDER_SAMPLE_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
