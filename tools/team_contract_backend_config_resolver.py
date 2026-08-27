#!/usr/bin/env python3
"""Pinned external-command resolver for portable backend configuration references."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import team_contract_package as package_tool
import team_contract_registry as registry_tool
import team_contract_registry_leader_backend as backend_tool
import team_contract_adapter_runtime as adapter_runtime


CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractBackendConfigResolverConfig"
REFERENCE_PRODUCT = "PocoDDSRuntimeTeamContractBackendConfigReference"
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractBackendConfigResolverRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractBackendConfigResolverResponse"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractBackendConfigResolverCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractBackendConfigResolverCapabilityManifest"
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _regular_pinned_file(path_value: str, expected_sha: str, label: str) -> Path:
    return adapter_runtime.regular_pinned_file(
        path_value, expected_sha, label
    )


def validate_reference(document: Any, *, resolver_id: str | None = None) \
        -> dict[str, Any]:
    fields = {"kind", "resolverId", "configId", "backendId", "revision"}
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("kind") != "backend-config-ref"
            or any(not package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, "")))
                for name in ("resolverId", "configId", "backendId", "revision"))
            or (resolver_id is not None
                and document["resolverId"] != resolver_id)):
        raise ValueError("backend configuration reference is malformed or out of scope")
    return document


def validate_config(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "resolverId", "kind", "configIds",
        "protocolMajor", "minimumProtocolMinor", "requiredCapabilities",
        "executable", "executableSha256", "arguments", "artifactPins",
        "environmentVariables", "timeoutSeconds", "maxResponseBytes",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CONFIG_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("resolverId", "")))
            or document.get("kind") != "external-command"
            or not isinstance(document.get("configIds"), list)
            or not document["configIds"]
            or len(document["configIds"]) > 128
            or document["configIds"] != sorted(set(document["configIds"]))
            or any(not package_tool.IDENTIFIER.fullmatch(str(item))
                   for item in document["configIds"])
            or type(document.get("protocolMajor")) is not int
            or not 1 <= document["protocolMajor"] <= 65535
            or type(document.get("minimumProtocolMinor")) is not int
            or not 0 <= document["minimumProtocolMinor"] <= 65535
            or not isinstance(document.get("requiredCapabilities"), list)
            or not document["requiredCapabilities"]
            or document["requiredCapabilities"]
                != sorted(set(document["requiredCapabilities"]))
            or len(document["requiredCapabilities"]) > 32
            or any(not isinstance(item, str)
                   or CAPABILITY_ID.fullmatch(item) is None
                   for item in document["requiredCapabilities"])
            or not isinstance(document.get("executable"), str)
            or not package_tool.SHA256.fullmatch(
                str(document.get("executableSha256", "")))
            or not isinstance(document.get("arguments"), list)
            or len(document["arguments"]) > 32
            or any(not isinstance(item, str) or not item
                   or len(item) > 1024 or "\x00" in item
                   for item in document["arguments"])
            or not isinstance(document.get("artifactPins"), list)
            or len(document["artifactPins"]) > 32
            or not isinstance(document.get("environmentVariables"), list)
            or len(document["environmentVariables"]) > 32
            or document["environmentVariables"]
                != sorted(set(document["environmentVariables"]))
            or any(ENVIRONMENT_NAME.fullmatch(str(item)) is None
                   for item in document["environmentVariables"])
            or type(document.get("timeoutSeconds")) is not int
            or not 1 <= document["timeoutSeconds"] <= 30
            or type(document.get("maxResponseBytes")) is not int
            or not 1024 <= document["maxResponseBytes"] <= 1024 * 1024):
        raise ValueError("backend configuration resolver config is malformed")
    seen: set[str] = set()
    for item in document["artifactPins"]:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                or not isinstance(item.get("path"), str)
                or item["path"] in seen
                or not package_tool.SHA256.fullmatch(
                    str(item.get("sha256", "")))):
            raise ValueError("backend configuration resolver artifact pin is malformed")
        seen.add(item["path"])


def load_config(path_value: str | Path, expected_sha: str) \
        -> tuple[dict[str, Any], Path, str]:
    path = package_tool.resolved_path(
        path_value, "backend configuration resolver config"
    )
    content = path.read_bytes()
    digest = package_tool.sha256_bytes(content)
    expected = str(expected_sha).lower()
    if not package_tool.SHA256.fullmatch(expected) or digest != expected:
        raise ValueError("backend configuration resolver identity is not pinned")
    document = json.loads(content)
    validate_config(document)
    _regular_pinned_file(
        document["executable"], document["executableSha256"],
        "backend configuration resolver executable",
    )
    for artifact in document["artifactPins"]:
        _regular_pinned_file(
            artifact["path"], artifact["sha256"],
            "backend configuration resolver artifact",
        )
    return document, path, digest


def _capability_request(resolver_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": CAPABILITY_REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "resolverId": resolver_id,
    }


def _request(resolver_id: str, reference: dict[str, Any],
             authority_id: str, registry_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "resolverId": resolver_id,
        "operation": "resolve", "reference": reference,
        "authorityId": authority_id, "registryId": registry_id,
    }


def validate_capability_manifest(document: Any,
                                 request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "resolverId",
        "implementationId", "protocolMajor", "protocolMinor", "capabilities",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CAPABILITY_MANIFEST_PRODUCT
            or document.get("requestId") != request["requestId"]
            or document.get("resolverId") != request["resolverId"]
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("implementationId", "")))
            or type(document.get("protocolMajor")) is not int
            or type(document.get("protocolMinor")) is not int
            or not isinstance(document.get("capabilities"), list)
            or not document["capabilities"]
            or document["capabilities"]
                != sorted(set(document["capabilities"]))
            or any(not isinstance(item, str)
                   or CAPABILITY_ID.fullmatch(item) is None
                   for item in document["capabilities"])):
        raise ValueError("backend configuration resolver capabilities are malformed")


def validate_response(document: Any, request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "resolverId", "operation",
        "passed", "reference", "configPath", "configSha256", "error",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != RESPONSE_PRODUCT
            or document.get("requestId") != request["requestId"]
            or document.get("resolverId") != request["resolverId"]
            or document.get("operation") != "resolve"
            or type(document.get("passed")) is not bool
            or document.get("reference") != request["reference"]
            or (document.get("error") is not None
                and (not isinstance(document["error"], str)
                     or not 1 <= len(document["error"]) <= 1024))):
        raise ValueError("backend configuration resolver response is malformed")
    if document["passed"]:
        if (document["error"] is not None
                or not isinstance(document.get("configPath"), str)
                or not Path(document["configPath"]).is_absolute()
                or not package_tool.SHA256.fullmatch(
                    str(document.get("configSha256", "")))):
            raise ValueError("backend configuration resolver success is malformed")
    elif (document["error"] is None or document["configPath"] is not None
          or document["configSha256"] is not None):
        raise ValueError("backend configuration resolver failure is malformed")


class ExternalCommandBackendConfigResolver:
    def __init__(self, config_path: str | Path,
                 expected_config_sha256: str) -> None:
        self.config, self.config_path, self.config_sha256 = load_config(
            config_path, expected_config_sha256
        )
        request = _capability_request(self.resolver_id)
        manifest = self._invoke(request, configured_environment=False)
        validate_capability_manifest(manifest, request)
        adapter_runtime.enforce_capability_policy(
            self.config, manifest, "backend configuration resolver"
        )
        self.capability_manifest = manifest
        self.capability_manifest_sha256 = adapter_runtime.capability_digest(
            manifest, "resolverId"
        )

    @property
    def resolver_id(self) -> str:
        return str(self.config["resolverId"])

    def descriptor(self) -> dict[str, Any]:
        return {
            "kind": "external-command", "resolverId": self.resolver_id,
            "configPath": str(self.config_path),
            "configSha256": self.config_sha256,
            "capabilityManifestSha256": self.capability_manifest_sha256,
        }

    def _invoke(self, request: dict[str, Any], *,
                configured_environment: bool = True) -> dict[str, Any]:
        config, path, digest = load_config(
            self.config_path, self.config_sha256
        )
        if config != self.config or path != self.config_path \
                or digest != self.config_sha256:
            raise ValueError("backend configuration resolver config changed")
        environment = adapter_runtime.isolated_environment(
            config["environmentVariables"],
            require_required=configured_environment,
            label="backend configuration resolver",
        )
        command = [str(Path(config["executable"]).resolve()), *config["arguments"]]
        return adapter_runtime.invoke_json(
            command, request, environment=environment,
            timeout_seconds=config["timeoutSeconds"],
            max_response_bytes=config["maxResponseBytes"],
            label="backend configuration resolver", expose_stderr=False,
        )

    def resolve(self, reference: dict[str, Any], authority_id: str,
                registry_id: str) -> backend_tool.ExternalCommandBackend:
        validate_reference(reference, resolver_id=self.resolver_id)
        if reference["configId"] not in self.config["configIds"]:
            raise ValueError("backend configuration reference is not authorized")
        request = _request(
            self.resolver_id, reference, authority_id, registry_id
        )
        response = self._invoke(request)
        validate_response(response, request)
        if not response["passed"]:
            raise RuntimeError(
                f"backend configuration resolver rejected request: {response['error']}"
            )
        backend = backend_tool.ExternalCommandBackend(
            response["configPath"], response["configSha256"],
            authority_id, registry_id,
        )
        if backend.backend_id != reference["backendId"]:
            raise ValueError("resolved backend identity does not match reference")
        return backend


def resolve_command(args: argparse.Namespace) -> int:
    try:
        reference_path = package_tool.resolved_path(
            args.reference, "backend configuration reference"
        )
        reference = json.loads(reference_path.read_bytes())
        resolver = ExternalCommandBackendConfigResolver(
            args.config, args.expected_config_sha256
        )
        backend = resolver.resolve(
            reference, args.authority_id, args.registry_id
        )
        report = {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractBackendConfigResolution",
            "passed": True, "reference": reference,
            "resolver": resolver.descriptor(),
            "resolvedBackend": backend.descriptor(),
        }
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print(
            "PDR_BACKEND_CONFIG_RESOLVE_PASS "
            f"resolver={resolver.resolver_id} config={reference['configId']} "
            f"backend={backend.backend_id} revision={reference['revision']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_BACKEND_CONFIG_RESOLVE_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", required=True)
    result.add_argument("--expected-config-sha256", required=True)
    result.add_argument("--reference", required=True)
    result.add_argument("--authority-id", required=True)
    result.add_argument("--registry-id", required=True)
    result.add_argument("--report")
    result.set_defaults(handler=resolve_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
