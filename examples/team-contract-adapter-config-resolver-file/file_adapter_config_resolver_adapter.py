#!/usr/bin/env python3
"""Reference resolver for host-local typed Adapter configuration mappings."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


MAPPING_PRODUCT = "PocoDDSRuntimeTeamContractAdapterConfigResolverMapping"
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractAdapterConfigResolverRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractAdapterConfigResolverResponse"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterConfigResolverCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterConfigResolverCapabilityManifest"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ADAPTER_KINDS = {
    "artifact-store", "control-authorizer", "fleet-executor",
    "registry-leader-backend", "wave-gate",
}
CAPABILITIES = [
    "adapter-identity-binding", "adapter-kind-binding",
    "consumer-scope-confinement", "local-path-resolution",
    "pinned-config-resolution", "revision-binding",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_mapping(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(
            "Adapter resolver mapping must be an absolute non-link file"
        )
    path = path.resolve()
    if not path.is_file():
        raise ValueError("Adapter resolver mapping must be a regular non-link file")
    document = json.loads(path.read_bytes())
    if (not isinstance(document, dict) or set(document) != {
            "schemaVersion", "product", "resolverId", "entries"
            } or document.get("schemaVersion") != 1
            or document.get("product") != MAPPING_PRODUCT
            or IDENTIFIER.fullmatch(str(
                document.get("resolverId", ""))) is None
            or not isinstance(document.get("entries"), list)
            or not 1 <= len(document["entries"]) <= 256):
        raise ValueError("Adapter resolver mapping is malformed")
    seen: set[str] = set()
    for entry in document["entries"]:
        if (not isinstance(entry, dict) or set(entry) != {
                "configId", "revision", "adapterKind", "adapterId",
                "configPath", "configSha256", "scopes",
                } or entry.get("adapterKind") not in ADAPTER_KINDS
                or any(IDENTIFIER.fullmatch(str(entry.get(name, ""))) is None
                       for name in ("configId", "revision", "adapterId"))
                or entry["configId"] in seen
                or not isinstance(entry.get("configPath"), str)
                or not Path(entry["configPath"]).is_absolute()
                or SHA256.fullmatch(str(
                    entry.get("configSha256", ""))) is None
                or not isinstance(entry.get("scopes"), list)
                or not entry["scopes"]):
            raise ValueError("Adapter resolver mapping entry is malformed")
        encoded_scopes = []
        for scope in entry["scopes"]:
            if (not isinstance(scope, dict) or set(scope) != {
                    "consumerType", "consumerId", "resourceId"
                    } or any(IDENTIFIER.fullmatch(str(
                        scope.get(name, ""))) is None for name in (
                            "consumerType", "consumerId", "resourceId"
                        ))):
                raise ValueError("Adapter resolver scope is malformed")
            encoded_scopes.append(json.dumps(scope, sort_keys=True))
        if encoded_scopes != sorted(set(encoded_scopes)):
            raise ValueError("Adapter resolver scopes are not sorted and unique")
        config_source = Path(entry["configPath"])
        if config_source.is_symlink():
            raise ValueError("resolved Adapter config must not be a link")
        config = config_source.resolve()
        if not config.is_file() \
                or digest(config) != entry["configSha256"]:
            raise ValueError("resolved Adapter config is absent or changed")
        seen.add(entry["configId"])
    if document["entries"] != sorted(
            document["entries"], key=lambda item: item["configId"]):
        raise ValueError("Adapter resolver entries are not sorted")
    return document


def read_request() -> dict[str, Any]:
    content = sys.stdin.buffer.read(1024 * 1024 + 1)
    if not content or len(content) > 1024 * 1024:
        raise ValueError("Adapter resolver request size is outside policy")
    document = json.loads(content)
    if not isinstance(document, dict):
        raise ValueError("Adapter resolver request is malformed")
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
        "scope": request.get("scope"), "configPath": config_path,
        "configSha256": config_sha, "error": error,
    }


def execute(request: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    if (set(request) != {
            "schemaVersion", "product", "requestId", "resolverId",
            "operation", "reference", "scope"
            } or request.get("schemaVersion") != 1
            or request.get("product") != REQUEST_PRODUCT
            or request.get("operation") != "resolve"
            or request.get("resolverId") != mapping["resolverId"]):
        raise ValueError("Adapter resolver request is malformed")
    reference = request["reference"]
    scope = request["scope"]
    if (not isinstance(reference, dict) or set(reference) != {
            "kind", "resolverId", "configId", "adapterKind", "adapterId",
            "revision"
            } or reference.get("kind") != "adapter-config-ref"
            or reference.get("resolverId") != mapping["resolverId"]
            or reference.get("adapterKind") not in ADAPTER_KINDS
            or any(IDENTIFIER.fullmatch(str(reference.get(name, ""))) is None
                   for name in (
                       "configId", "adapterId", "revision"
                   )) or not isinstance(scope, dict) or set(scope) != {
                       "consumerType", "consumerId", "resourceId"
                   } or any(IDENTIFIER.fullmatch(str(
                       scope.get(name, ""))) is None for name in (
                           "consumerType", "consumerId", "resourceId"
                       ))):
        raise ValueError("Adapter resolver request identity is malformed")
    selected = next((
        item for item in mapping["entries"]
        if item["configId"] == reference["configId"]
    ), None)
    if selected is None:
        return response(request, passed=False, error="configuration not found")
    if (selected["revision"] != reference["revision"]
            or selected["adapterKind"] != reference["adapterKind"]
            or selected["adapterId"] != reference["adapterId"]):
        return response(request, passed=False, error="configuration identity changed")
    if scope not in selected["scopes"]:
        return response(request, passed=False, error="consumer scope is not authorized")
    config_source = Path(selected["configPath"])
    if config_source.is_symlink():
        return response(request, passed=False, error="configuration path changed")
    config = config_source.resolve()
    if not config.is_file() \
            or digest(config) != selected["configSha256"]:
        return response(request, passed=False, error="configuration content changed")
    return response(
        request, passed=True, config_path=str(config),
        config_sha=selected["configSha256"],
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
                raise ValueError("Adapter resolver capability request is malformed")
            result = {
                "schemaVersion": 1, "product": CAPABILITY_MANIFEST_PRODUCT,
                "requestId": request["requestId"],
                "resolverId": request["resolverId"],
                "implementationId": "pdr-file-adapter-config-resolver-v1",
                "protocolMajor": 1, "protocolMinor": 0,
                "capabilities": CAPABILITIES,
            }
        else:
            result = execute(request, mapping)
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CONFIG_RESOLVER_SAMPLE_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
