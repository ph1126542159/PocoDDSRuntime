#!/usr/bin/env python3
"""Pinned resolver for portable, typed Adapter configuration references."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import team_contract_adapter_runtime as adapter_runtime
import team_contract_package as package_tool


CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractAdapterConfigResolverConfig"
REFERENCE_PRODUCT = "PocoDDSRuntimeTeamContractAdapterConfigReference"
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractAdapterConfigResolverRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractAdapterConfigResolverResponse"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterConfigResolverCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterConfigResolverCapabilityManifest"
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ADAPTER_TYPES = {
    "artifact-store": (
        "PocoDDSRuntimeTeamContractArtifactStoreConfig", "storeId"
    ),
    "control-authorizer": (
        "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerConfig",
        "authorizerId",
    ),
    "fleet-executor": (
        "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorConfig",
        "executorId",
    ),
    "registry-leader-backend": (
        "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig", "backendId"
    ),
    "wave-gate": (
        "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateConfig", "gateId"
    ),
}
REQUIRED_CAPABILITIES = [
    "adapter-identity-binding", "adapter-kind-binding",
    "consumer-scope-confinement", "local-path-resolution",
    "pinned-config-resolution", "revision-binding",
]


def validate_reference(document: Any, *, resolver_id: str | None = None,
                       adapter_kind: str | None = None) -> dict[str, Any]:
    fields = {
        "kind", "resolverId", "configId", "adapterKind", "adapterId",
        "revision",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("kind") != "adapter-config-ref"
            or document.get("adapterKind") not in ADAPTER_TYPES
            or any(package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, ""))) is None
                for name in (
                    "resolverId", "configId", "adapterId", "revision"
                ))
            or (resolver_id is not None
                and document["resolverId"] != resolver_id)
            or (adapter_kind is not None
                and document["adapterKind"] != adapter_kind)):
        raise ValueError(
            "Adapter configuration reference is malformed or out of scope"
        )
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
            or package_tool.IDENTIFIER.fullmatch(str(
                document.get("resolverId", ""))) is None
            or document.get("kind") != "external-command"
            or not isinstance(document.get("configIds"), list)
            or not document["configIds"]
            or len(document["configIds"]) > 256
            or document["configIds"] != sorted(set(document["configIds"]))
            or any(package_tool.IDENTIFIER.fullmatch(str(item)) is None
                   for item in document["configIds"])
            or type(document.get("protocolMajor")) is not int
            or not 1 <= document["protocolMajor"] <= 65535
            or type(document.get("minimumProtocolMinor")) is not int
            or not 0 <= document["minimumProtocolMinor"] <= 65535
            or document.get("requiredCapabilities") != REQUIRED_CAPABILITIES
            or not isinstance(document.get("executable"), str)
            or package_tool.SHA256.fullmatch(str(
                document.get("executableSha256", ""))) is None
            or not isinstance(document.get("arguments"), list)
            or len(document["arguments"]) > 32
            or any(not isinstance(item, str) or not item or "\x00" in item
                   or len(item) > 1024 for item in document["arguments"])
            or type(document.get("timeoutSeconds")) is not int
            or not 1 <= document["timeoutSeconds"] <= 30
            or type(document.get("maxResponseBytes")) is not int
            or not 1024 <= document["maxResponseBytes"] <= 1024 * 1024):
        raise ValueError("Adapter configuration resolver config is malformed")
    adapter_runtime.validate_artifact_pins(
        document["artifactPins"], "Adapter configuration resolver"
    )
    adapter_runtime.validate_environment_policy(
        document["environmentVariables"],
        label="Adapter configuration resolver",
    )


def load_config(path_value: str | Path, expected_sha: str) \
        -> tuple[dict[str, Any], Path, str]:
    config, path, digest = adapter_runtime.load_pinned_json(
        path_value, expected_sha, "Adapter configuration resolver config",
        validate_config,
    )
    adapter_runtime.revalidate_artifacts(
        config, "Adapter configuration resolver"
    )
    return config, path, digest


def _scope(consumer_type: str, consumer_id: str,
           resource_id: str) -> dict[str, str]:
    if any(package_tool.IDENTIFIER.fullmatch(value) is None for value in (
            consumer_type, consumer_id, resource_id)):
        raise ValueError("Adapter configuration consumer scope is malformed")
    return {
        "consumerType": consumer_type,
        "consumerId": consumer_id,
        "resourceId": resource_id,
    }


def _capability_request(resolver_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": CAPABILITY_REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "resolverId": resolver_id,
    }


def _request(resolver_id: str, reference: dict[str, Any],
             scope: dict[str, str]) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "resolverId": resolver_id,
        "operation": "resolve", "reference": reference, "scope": scope,
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
            or package_tool.IDENTIFIER.fullmatch(str(
                document.get("implementationId", ""))) is None
            or type(document.get("protocolMajor")) is not int
            or type(document.get("protocolMinor")) is not int
            or not isinstance(document.get("capabilities"), list)
            or document["capabilities"] != sorted(set(
                document["capabilities"]))
            or any(CAPABILITY_ID.fullmatch(str(item)) is None
                   for item in document["capabilities"])):
        raise ValueError(
            "Adapter configuration resolver capabilities are malformed"
        )


def validate_response(document: Any, request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "resolverId", "operation",
        "passed", "reference", "scope", "configPath", "configSha256",
        "error",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != RESPONSE_PRODUCT
            or document.get("requestId") != request["requestId"]
            or document.get("resolverId") != request["resolverId"]
            or document.get("operation") != "resolve"
            or type(document.get("passed")) is not bool
            or document.get("reference") != request["reference"]
            or document.get("scope") != request["scope"]
            or (document.get("error") is not None
                and (not isinstance(document["error"], str)
                     or not 1 <= len(document["error"]) <= 1024))):
        raise ValueError("Adapter configuration resolver response is malformed")
    if document["passed"]:
        if (document["error"] is not None
                or not isinstance(document.get("configPath"), str)
                or not Path(document["configPath"]).is_absolute()
                or package_tool.SHA256.fullmatch(str(
                    document.get("configSha256", ""))) is None):
            raise ValueError(
                "Adapter configuration resolver success is malformed"
            )
    elif (document["error"] is None or document["configPath"] is not None
          or document["configSha256"] is not None):
        raise ValueError("Adapter configuration resolver failure is malformed")


class ExternalCommandAdapterConfigResolver:
    def __init__(self, config_path: str | Path,
                 expected_config_sha256: str) -> None:
        self.config, self.config_path, self.config_sha256 = load_config(
            config_path, expected_config_sha256
        )
        request = _capability_request(self.resolver_id)
        manifest = self._invoke(request, configured_environment=False)
        validate_capability_manifest(manifest, request)
        adapter_runtime.enforce_capability_policy(
            self.config, manifest, "Adapter configuration resolver"
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
            raise ValueError("Adapter configuration resolver config changed")
        environment = adapter_runtime.isolated_environment(
            config["environmentVariables"],
            require_required=configured_environment,
            label="Adapter configuration resolver",
        )
        return adapter_runtime.invoke_json(
            [str(Path(config["executable"]).resolve()), *config["arguments"]],
            request, environment=environment,
            timeout_seconds=config["timeoutSeconds"],
            max_response_bytes=config["maxResponseBytes"],
            label="Adapter configuration resolver", expose_stderr=False,
        )

    def resolve(self, reference: dict[str, Any], *, consumer_type: str,
                consumer_id: str, resource_id: str) \
            -> tuple[dict[str, Any], Path, str]:
        validate_reference(reference, resolver_id=self.resolver_id)
        if reference["configId"] not in self.config["configIds"]:
            raise ValueError("Adapter configuration reference is not authorized")
        scope = _scope(consumer_type, consumer_id, resource_id)
        request = _request(self.resolver_id, reference, scope)
        response = self._invoke(request)
        validate_response(response, request)
        if not response["passed"]:
            raise RuntimeError(
                "Adapter configuration resolver rejected request: "
                f"{response['error']}"
            )
        expected_product, identity_field = ADAPTER_TYPES[
            reference["adapterKind"]
        ]
        document, path, digest = adapter_runtime.load_pinned_json(
            response["configPath"], response["configSha256"],
            "resolved Adapter config", lambda item: None,
        )
        if (not isinstance(document, dict)
                or document.get("product") != expected_product
                or document.get(identity_field) != reference["adapterId"]):
            raise ValueError("resolved Adapter config identity changed")
        return document, path, digest


def parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Adapter Config Resolver SPI library; Fleet commands consume it "
            "through a pinned local resolver config"
        )
    )


def main() -> int:
    parser().parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

