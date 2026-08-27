#!/usr/bin/env python3
"""Reference adapter that resolves logical backend config IDs from a pinned map."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


MAPPING_PRODUCT = "PocoDDSRuntimeTeamContractBackendConfigResolverMapping"
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractBackendConfigResolverRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractBackendConfigResolverResponse"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractBackendConfigResolverCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractBackendConfigResolverCapabilityManifest"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CAPABILITIES = [
    "backend-identity-binding", "local-path-resolution",
    "pinned-config-resolution", "revision-binding", "scope-validation",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_mapping(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("resolver mapping path must be absolute")
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError("resolver mapping must be a regular non-link file")
    document = json.loads(path.read_bytes())
    fields = {"schemaVersion", "product", "resolverId", "entries"}
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != MAPPING_PRODUCT
            or not IDENTIFIER.fullmatch(str(document.get("resolverId", "")))
            or not isinstance(document.get("entries"), list)
            or not document["entries"] or len(document["entries"]) > 128):
        raise ValueError("resolver mapping is malformed")
    seen: set[str] = set()
    for entry in document["entries"]:
        if (not isinstance(entry, dict)
                or set(entry) != {
                    "configId", "backendId", "revision", "configPath",
                    "configSha256",
                }
                or any(not IDENTIFIER.fullmatch(str(entry.get(name, "")))
                       for name in ("configId", "backendId", "revision"))
                or entry["configId"] in seen
                or not isinstance(entry.get("configPath"), str)
                or not Path(entry["configPath"]).is_absolute()
                or not SHA256.fullmatch(str(entry.get("configSha256", "")))):
            raise ValueError("resolver mapping entry is malformed")
        config = Path(entry["configPath"]).resolve()
        if config.is_symlink() or not config.is_file() \
                or digest(config) != entry["configSha256"]:
            raise ValueError("resolved backend config is absent or changed")
        seen.add(entry["configId"])
    return document


def read_request() -> dict[str, Any]:
    content = sys.stdin.buffer.read(1024 * 1024 + 1)
    if not content or len(content) > 1024 * 1024:
        raise ValueError("resolver request size is outside policy")
    document = json.loads(content)
    if not isinstance(document, dict):
        raise ValueError("resolver request is malformed")
    return document


def response(request: dict[str, Any], *, passed: bool,
             config_path: str | None = None,
             config_sha: str | None = None,
             error: str | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": RESPONSE_PRODUCT,
        "requestId": request.get("requestId"),
        "resolverId": request.get("resolverId"), "operation": "resolve",
        "passed": passed, "reference": request.get("reference"),
        "configPath": config_path, "configSha256": config_sha,
        "error": error,
    }


def execute(request: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "schemaVersion", "product", "requestId", "resolverId", "operation",
        "reference", "authorityId", "registryId",
    }
    reference = request.get("reference")
    if (set(request) != fields or request.get("schemaVersion") != 1
            or request.get("product") != REQUEST_PRODUCT
            or request.get("operation") != "resolve"
            or request.get("resolverId") != mapping["resolverId"]
            or any(not IDENTIFIER.fullmatch(str(request.get(name, "")))
                   for name in (
                       "requestId", "resolverId", "authorityId", "registryId"
                   ))
            or not isinstance(reference, dict)
            or set(reference) != {
                "kind", "resolverId", "configId", "backendId", "revision"
            }
            or reference.get("kind") != "backend-config-ref"
            or reference.get("resolverId") != mapping["resolverId"]
            or any(not IDENTIFIER.fullmatch(str(reference.get(name, "")))
                   for name in ("configId", "backendId", "revision"))):
        raise ValueError("resolver request is malformed or out of scope")
    selected = [
        item for item in mapping["entries"]
        if item["configId"] == reference["configId"]
    ]
    if not selected:
        return response(request, passed=False, error="configuration not found")
    entry = selected[0]
    if (entry["backendId"] != reference["backendId"]
            or entry["revision"] != reference["revision"]):
        return response(request, passed=False, error="configuration identity changed")
    config = Path(entry["configPath"]).resolve()
    if config.is_symlink() or not config.is_file() \
            or digest(config) != entry["configSha256"]:
        return response(request, passed=False, error="configuration content changed")
    return response(
        request, passed=True, config_path=str(config),
        config_sha=entry["configSha256"],
    )


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
                    "schemaVersion", "product", "requestId", "resolverId"
                } or request.get("schemaVersion") != 1
                    or request.get("resolverId") != mapping["resolverId"]):
                raise ValueError("resolver capability request is malformed")
            result = {
                "schemaVersion": 1, "product": CAPABILITY_MANIFEST_PRODUCT,
                "requestId": request["requestId"],
                "resolverId": request["resolverId"],
                "implementationId": "pdr-file-backend-config-resolver-v1",
                "protocolMajor": 1, "protocolMinor": 0,
                "capabilities": CAPABILITIES,
            }
        else:
            result = execute(request, mapping)
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_BACKEND_CONFIG_RESOLVER_SAMPLE_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
