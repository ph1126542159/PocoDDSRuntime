#!/usr/bin/env python3
"""Pinned external authorization boundary for Adapter Catalog Fleet controls."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import team_contract_adapter_runtime as adapter_runtime
import team_contract_package as package_tool


CONFIG_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerConfig"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerCapabilityManifest"
REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerRequest"
RESPONSE_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerResponse"
REQUIRED_CAPABILITIES = [
    "deny-by-default", "idempotent-control-authorization",
    "no-secret-evidence", "principal-binding", "sanitized-control-intent",
]


def validate_config(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "authorizerId", "kind", "protocolMajor",
        "minimumProtocolMinor", "requiredCapabilities", "executable",
        "executableSha256", "arguments", "artifactPins",
        "environmentVariables", "optionalEnvironmentVariables",
        "timeoutSeconds", "maxResponseBytes",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CONFIG_PRODUCT
            or package_tool.IDENTIFIER.fullmatch(
                str(document.get("authorizerId", ""))) is None
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
            or not 1 <= document["timeoutSeconds"] <= 120
            or type(document.get("maxResponseBytes")) is not int
            or not 1024 <= document["maxResponseBytes"] <= 1024 * 1024):
        raise ValueError("Adapter Catalog Control Authorizer config is malformed")
    adapter_runtime.validate_artifact_pins(document["artifactPins"],
                                           "control authorizer")
    adapter_runtime.validate_environment_policy(
        document["environmentVariables"],
        optional=document["optionalEnvironmentVariables"],
        label="control authorizer",
    )


def load_config(path_value: str | Path, expected_sha: str) \
        -> tuple[dict[str, Any], Path, str]:
    config, path, digest = adapter_runtime.load_pinned_json(
        path_value, expected_sha, "Adapter Catalog Control Authorizer config",
        validate_config,
    )
    adapter_runtime.revalidate_artifacts(config, "control authorizer")
    return config, path, digest


def invoke(config: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    adapter_runtime.revalidate_artifacts(config, "control authorizer")
    environment = adapter_runtime.isolated_environment(
        config["environmentVariables"],
        optional=config["optionalEnvironmentVariables"],
        require_required=True, label="control authorizer",
    )
    return adapter_runtime.invoke_json(
        [str(Path(config["executable"]).resolve()), *config["arguments"]],
        request, environment=environment,
        timeout_seconds=config["timeoutSeconds"],
        max_response_bytes=config["maxResponseBytes"],
        label="Adapter Catalog Control Authorizer", expose_stderr=False,
    )


def negotiate(config: dict[str, Any]) -> str:
    request = {
        "schemaVersion": 1, "product": CAPABILITY_REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()),
        "authorizerId": config["authorizerId"],
    }
    response = invoke(config, request)
    fields = {
        "schemaVersion", "product", "requestId", "authorizerId",
        "implementationId", "protocolMajor", "protocolMinor", "capabilities",
    }
    if (not isinstance(response, dict) or set(response) != fields
            or response.get("schemaVersion") != 1
            or response.get("product") != CAPABILITY_MANIFEST_PRODUCT
            or response.get("requestId") != request["requestId"]
            or response.get("authorizerId") != config["authorizerId"]
            or package_tool.IDENTIFIER.fullmatch(
                str(response.get("implementationId", ""))) is None
            or type(response.get("protocolMajor")) is not int
            or type(response.get("protocolMinor")) is not int
            or not isinstance(response.get("capabilities"), list)
            or response["capabilities"] != sorted(set(response["capabilities"]))
            or any(adapter_runtime.CAPABILITY_ID.fullmatch(str(item)) is None
                   for item in response["capabilities"])):
        raise ValueError("Control Authorizer capability manifest is malformed")
    adapter_runtime.enforce_capability_policy(
        config, response, "control authorizer"
    )
    return adapter_runtime.capability_digest(response, "authorizerId")


def validate_response(response: Any, request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "authorizerId",
        "authorizationId", "rolloutId", "operationId", "action", "allowed",
        "decision", "principalId", "evidenceSha256", "diagnosticCode",
    }
    if (not isinstance(response, dict) or set(response) != fields
            or response.get("schemaVersion") != 1
            or response.get("product") != RESPONSE_PRODUCT
            or any(response.get(name) != request[name] for name in (
                "requestId", "authorizerId", "authorizationId", "rolloutId",
                "operationId", "action"))
            or type(response.get("allowed")) is not bool
            or response.get("decision") not in {"allow", "deny"}
            or response["allowed"] != (response["decision"] == "allow")
            or package_tool.SHA256.fullmatch(
                str(response.get("evidenceSha256", ""))) is None
            or (response.get("principalId") is not None
                and package_tool.IDENTIFIER.fullmatch(
                    str(response["principalId"])) is None)
            or (response.get("diagnosticCode") is not None
                and package_tool.IDENTIFIER.fullmatch(
                    str(response["diagnosticCode"])) is None)
            or (response["allowed"] and
                response.get("principalId") != request["claimedActor"])
            or (response["allowed"] and response["diagnosticCode"] is not None)
            or (not response["allowed"] and response["diagnosticCode"] is None)):
        raise ValueError("Control Authorizer response is malformed or mismatched")


def authorize(config: dict[str, Any], *, rollout_id: str, operation_id: str,
              action: str, claimed_actor: str, reason_sha256: str,
              expected_control_generation: int, wave_id: str, wave_index: int,
              catalog_id: str, candidate_generation: int,
              candidate_sha256: str,
              gate_evidence_sha256: str | None) -> dict[str, Any]:
    authorization_id = f"{rollout_id}.{operation_id}"
    if package_tool.IDENTIFIER.fullmatch(authorization_id) is None:
        raise ValueError("Fleet control authorization identity is malformed")
    request = {
        "schemaVersion": 1, "product": REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()),
        "authorizerId": config["authorizerId"],
        "authorizationId": authorization_id, "rolloutId": rollout_id,
        "operationId": operation_id, "action": action,
        "claimedActor": claimed_actor, "reasonSha256": reason_sha256,
        "expectedControlGeneration": expected_control_generation,
        "waveId": wave_id, "waveIndex": wave_index,
        "catalogId": catalog_id,
        "candidateCatalogGeneration": candidate_generation,
        "candidateCatalogSha256": candidate_sha256,
        "gateEvidenceSha256": gate_evidence_sha256,
    }
    response = invoke(config, request)
    validate_response(response, request)
    return response


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        print("PDR_ADAPTER_CATALOG_CONTROL_AUTHORIZER_SELF_CHECK_PASS")
        return 0
    parser.error("--self-check is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
