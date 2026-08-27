#!/usr/bin/env python3
"""Pinned external Wave Gate boundary for Adapter Catalog Fleet rollout."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import team_contract_adapter_runtime as adapter_runtime
import team_contract_package as package_tool


CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateConfig"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateCapabilityManifest"
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateResponse"
REQUIRED_CAPABILITIES = [
    "bounded-observation", "idempotent-evaluation", "no-secret-evidence",
    "wave-slo-gate",
]


def validate_config(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "gateId", "kind", "protocolMajor",
        "minimumProtocolMinor", "requiredCapabilities", "executable",
        "executableSha256", "arguments", "artifactPins",
        "environmentVariables", "optionalEnvironmentVariables",
        "timeoutSeconds", "maxResponseBytes",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CONFIG_PRODUCT
            or package_tool.IDENTIFIER.fullmatch(
                str(document.get("gateId", ""))) is None
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
        raise ValueError("Adapter Catalog Wave Gate config is malformed")
    adapter_runtime.validate_artifact_pins(document["artifactPins"], "wave gate")
    adapter_runtime.validate_environment_policy(
        document["environmentVariables"],
        optional=document["optionalEnvironmentVariables"], label="wave gate",
    )


def load_config(path_value: str | Path, expected_sha: str) \
        -> tuple[dict[str, Any], Path, str]:
    config, path, digest = adapter_runtime.load_pinned_json(
        path_value, expected_sha, "Adapter Catalog Wave Gate config",
        validate_config,
    )
    adapter_runtime.revalidate_artifacts(config, "wave gate")
    return config, path, digest


def invoke(config: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    adapter_runtime.revalidate_artifacts(config, "wave gate")
    environment = adapter_runtime.isolated_environment(
        config["environmentVariables"],
        optional=config["optionalEnvironmentVariables"],
        require_required=True, label="wave gate",
    )
    return adapter_runtime.invoke_json(
        [str(Path(config["executable"]).resolve()), *config["arguments"]],
        request, environment=environment,
        timeout_seconds=config["timeoutSeconds"],
        max_response_bytes=config["maxResponseBytes"],
        label="Adapter Catalog Wave Gate", expose_stderr=False,
    )


def negotiate(config: dict[str, Any]) -> str:
    request = {
        "schemaVersion": 1, "product": CAPABILITY_REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "gateId": config["gateId"],
    }
    response = invoke(config, request)
    fields = {
        "schemaVersion", "product", "requestId", "gateId",
        "implementationId", "protocolMajor", "protocolMinor", "capabilities",
    }
    if (not isinstance(response, dict) or set(response) != fields
            or response.get("schemaVersion") != 1
            or response.get("product") != CAPABILITY_MANIFEST_PRODUCT
            or response.get("requestId") != request["requestId"]
            or response.get("gateId") != config["gateId"]
            or package_tool.IDENTIFIER.fullmatch(
                str(response.get("implementationId", ""))) is None
            or type(response.get("protocolMajor")) is not int
            or type(response.get("protocolMinor")) is not int
            or not isinstance(response.get("capabilities"), list)
            or response["capabilities"] != sorted(set(response["capabilities"]))
            or any(adapter_runtime.CAPABILITY_ID.fullmatch(str(item)) is None
                   for item in response["capabilities"])):
        raise ValueError("Wave Gate capability manifest is malformed")
    adapter_runtime.enforce_capability_policy(config, response, "wave gate")
    return adapter_runtime.capability_digest(response, "gateId")


def validate_response(response: Any, request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "gateId", "evaluationId",
        "rolloutId", "waveId", "attempt", "accepted", "decision",
        "evidenceSha256", "diagnosticCode",
    }
    if (not isinstance(response, dict) or set(response) != fields
            or response.get("schemaVersion") != 1
            or response.get("product") != RESPONSE_PRODUCT
            or any(response.get(name) != request[name] for name in (
                "requestId", "gateId", "evaluationId", "rolloutId", "waveId",
                "attempt"))
            or type(response.get("accepted")) is not bool
            or response.get("decision") not in {"pass", "pause", "fail"}
            or response["accepted"] != (response["decision"] == "pass")
            or (response.get("evidenceSha256") is not None
                and package_tool.SHA256.fullmatch(
                    str(response["evidenceSha256"])) is None)
            or (response.get("diagnosticCode") is not None
                and package_tool.IDENTIFIER.fullmatch(
                    str(response["diagnosticCode"])) is None)
            or (response["decision"] == "pass"
                and response["evidenceSha256"] is None)
            or (response["decision"] != "pass"
                and response["diagnosticCode"] is None)):
        raise ValueError("Wave Gate response is malformed or mismatched")


def evaluate(config: dict[str, Any], *, rollout_id: str, wave_id: str,
             wave_index: int, catalog_id: str, candidate_generation: int,
             candidate_sha: str, attempt: int,
             observation_started_at: str,
             node_counts: dict[str, int]) -> dict[str, Any]:
    evaluation_id = f"{rollout_id}.{wave_id}.{attempt}"
    if package_tool.IDENTIFIER.fullmatch(evaluation_id) is None:
        raise ValueError("Wave Gate evaluation identity is malformed")
    request = {
        "schemaVersion": 1, "product": REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "gateId": config["gateId"],
        "evaluationId": evaluation_id, "rolloutId": rollout_id,
        "waveId": wave_id, "waveIndex": wave_index,
        "catalogId": catalog_id,
        "candidateCatalogGeneration": candidate_generation,
        "candidateCatalogSha256": candidate_sha, "attempt": attempt,
        "observationStartedAt": observation_started_at,
        "nodeCounts": node_counts,
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
        print("PDR_ADAPTER_CATALOG_WAVE_GATE_SELF_CHECK_PASS")
        return 0
    parser.error("--self-check is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
