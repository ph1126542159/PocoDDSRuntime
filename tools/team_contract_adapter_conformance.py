#!/usr/bin/env python3
"""Certify a pinned Adapter against the common integration-readiness contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import team_contract_adapter_catalog_control_authorizer as authorizer_tool
import team_contract_adapter_catalog_fleet as fleet_tool
import team_contract_adapter_catalog_wave_gate as wave_gate_tool
import team_contract_adapter_config_resolver as resolver_tool
import team_contract_governance_approval_signer as approval_signer_tool
import team_contract_adapter_runtime as adapter_runtime
import team_contract_artifact_store as artifact_store_tool
import team_contract_package as package_tool
import team_contract_registry as registry_tool
import team_contract_registry_leader_backend as backend_tool


EVIDENCE_PRODUCT = "PocoDDSRuntimeTeamContractAdapterConformanceEvidence"
CHECK_SET_VERSION = "1.0.0"
CERTIFICATION_LEVEL = "integration-readiness"
SUPPORTED_KINDS = {
    "adapter-config-resolver": "resolverId",
    "artifact-store": "storeId",
    "control-authorizer": "authorizerId",
    "fleet-executor": "executorId",
    "governance-approval-signer": "signerId",
    "registry-leader-backend": "backendId",
    "wave-gate": "gateId",
}
CHECK_IDS = [
    "adapter-identity-bound",
    "artifact-pins-revalidated",
    "capability-negotiated",
    "capability-replay-stable",
    "config-pin-enforced",
    "config-revalidated",
    "environment-confined",
    "evidence-redacted",
    "process-policy-bounded",
]


def _scope(primary_id: str | None, secondary_id: str | None,
           adapter_kind: str) -> dict[str, str | None]:
    if any(value is not None and package_tool.IDENTIFIER.fullmatch(value) is None
           for value in (primary_id, secondary_id)):
        raise ValueError("Adapter conformance scope is malformed")
    if adapter_kind == "registry-leader-backend":
        if primary_id is None or secondary_id is None:
            raise ValueError(
                "Backend conformance requires primary and secondary scope IDs"
            )
    elif adapter_kind == "artifact-store":
        if primary_id is None or secondary_id is not None:
            raise ValueError(
                "Artifact Store conformance requires only a primary scope ID"
            )
    elif adapter_kind == "governance-approval-signer":
        if primary_id is None or secondary_id is not None:
            raise ValueError(
                "Governance Approval Signer conformance requires only an "
                "approver scope ID"
            )
    elif primary_id is not None or secondary_id is not None:
        raise ValueError(
            f"{adapter_kind} conformance does not accept scope IDs"
        )
    return {"primaryId": primary_id, "secondaryId": secondary_id}


def _load_adapter(adapter_kind: str, config_path: str | Path,
                  expected_sha256: str,
                  scope: dict[str, str | None]) \
        -> tuple[dict[str, Any], Path, str, str, str]:
    if adapter_kind == "fleet-executor":
        config, path, digest = fleet_tool.load_executor_config(
            config_path, expected_sha256
        )
        capability_sha256 = fleet_tool.negotiate(config)
    elif adapter_kind == "wave-gate":
        config, path, digest = wave_gate_tool.load_config(
            config_path, expected_sha256
        )
        capability_sha256 = wave_gate_tool.negotiate(config)
    elif adapter_kind == "control-authorizer":
        config, path, digest = authorizer_tool.load_config(
            config_path, expected_sha256
        )
        capability_sha256 = authorizer_tool.negotiate(config)
    elif adapter_kind == "adapter-config-resolver":
        adapter = resolver_tool.ExternalCommandAdapterConfigResolver(
            config_path, expected_sha256
        )
        config, path, digest = (
            adapter.config, adapter.config_path, adapter.config_sha256
        )
        capability_sha256 = adapter.capability_manifest_sha256
    elif adapter_kind == "artifact-store":
        primary_id = scope["primaryId"]
        assert primary_id is not None
        adapter = artifact_store_tool.ExternalCommandArtifactStore(
            config_path, expected_sha256, primary_id
        )
        config, path, digest = (
            adapter.config, adapter.config_path, adapter.config_sha256
        )
        capability_sha256 = adapter.capability_manifest_sha256
    elif adapter_kind == "registry-leader-backend":
        primary_id = scope["primaryId"]
        secondary_id = scope["secondaryId"]
        assert primary_id is not None and secondary_id is not None
        adapter = backend_tool.ExternalCommandBackend(
            config_path, expected_sha256, primary_id, secondary_id
        )
        config, path, digest = (
            adapter.config, adapter.config_path, adapter.config_sha256
        )
        if adapter.capability_manifest_sha256 is None:
            raise ValueError(
                "Backend conformance requires capability-aware config v2+"
            )
        capability_sha256 = adapter.capability_manifest_sha256
    elif adapter_kind == "governance-approval-signer":
        primary_id = scope["primaryId"]
        assert primary_id is not None
        adapter = approval_signer_tool.ExternalCommandGovernanceApprovalSigner(
            config_path, expected_sha256
        )
        config, path, digest = (
            adapter.config, adapter.config_path, adapter.config_sha256
        )
        if adapter.approver_id != primary_id:
            raise ValueError(
                "Governance Approval Signer approver scope changed"
            )
        capability_sha256 = adapter.capability_manifest_sha256
    else:
        raise ValueError("unsupported Adapter conformance kind")
    identity_field = SUPPORTED_KINDS[adapter_kind]
    adapter_id = str(config.get(identity_field, ""))
    if package_tool.IDENTIFIER.fullmatch(adapter_id) is None:
        raise ValueError("Adapter conformance identity is malformed")
    if package_tool.SHA256.fullmatch(capability_sha256) is None:
        raise ValueError("Adapter conformance capability identity is malformed")
    return config, path, digest, adapter_id, capability_sha256


def _check(check_id: str, evidence: Any) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "passed": True,
        "evidenceSha256": package_tool.sha256_bytes(
            package_tool.json_bytes(evidence)
        ),
        "diagnostic": None,
    }


def _report_digest(document: dict[str, Any]) -> str:
    return package_tool.sha256_bytes(package_tool.json_bytes({
        key: value for key, value in document.items()
        if key != "reportSha256"
    }))


def validate_evidence(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "passed", "certificationLevel",
        "checkSetVersion", "conformanceId", "adapterKind", "adapterId",
        "configSchemaVersion", "configSha256", "scope", "protocol",
        "requiredCapabilities", "capabilityManifestSha256", "checks",
        "certifiedAt", "reportSha256",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != EVIDENCE_PRODUCT
            or document.get("passed") is not True
            or document.get("certificationLevel") != CERTIFICATION_LEVEL
            or document.get("checkSetVersion") != CHECK_SET_VERSION
            or document.get("adapterKind") not in SUPPORTED_KINDS
            or package_tool.IDENTIFIER.fullmatch(str(
                document.get("adapterId", ""))) is None
            or any(package_tool.SHA256.fullmatch(str(
                document.get(name, ""))) is None for name in (
                    "conformanceId", "configSha256",
                    "capabilityManifestSha256", "reportSha256",
                ))
            or type(document.get("configSchemaVersion")) is not int
            or not 1 <= document["configSchemaVersion"] <= 65535
            or not isinstance(document.get("scope"), dict)
            or set(document["scope"]) != {"primaryId", "secondaryId"}
            or not isinstance(document.get("protocol"), dict)
            or set(document["protocol"]) != {"major", "minimumMinor"}
            or type(document["protocol"].get("major")) is not int
            or type(document["protocol"].get("minimumMinor")) is not int
            or not 1 <= document["protocol"]["major"] <= 65535
            or not 0 <= document["protocol"]["minimumMinor"] <= 65535
            or not isinstance(document.get("requiredCapabilities"), list)
            or not 1 <= len(document["requiredCapabilities"]) <= 32
            or document["requiredCapabilities"] != sorted(set(
                document["requiredCapabilities"]))
            or any(adapter_runtime.CAPABILITY_ID.fullmatch(str(item)) is None
                   for item in document["requiredCapabilities"])
            or not isinstance(document.get("checks"), list)
            or [item.get("checkId") for item in document["checks"]]
                != CHECK_IDS
            or document["reportSha256"] != _report_digest(document)):
        raise ValueError("Adapter conformance evidence is malformed")
    _scope(
        document["scope"]["primaryId"], document["scope"]["secondaryId"],
        document["adapterKind"],
    )
    package_tool.parse_time(document.get("certifiedAt"), "certifiedAt")
    for item in document["checks"]:
        if (not isinstance(item, dict) or set(item) != {
                "checkId", "passed", "evidenceSha256", "diagnostic"
                } or item.get("passed") is not True
                or package_tool.SHA256.fullmatch(str(
                    item.get("evidenceSha256", ""))) is None
                or item.get("diagnostic") is not None):
            raise ValueError("Adapter conformance check evidence is malformed")


def execute_command(args: argparse.Namespace) -> int:
    try:
        adapter_kind = str(args.adapter_kind)
        if adapter_kind not in SUPPORTED_KINDS:
            raise ValueError("unsupported Adapter conformance kind")
        scope = _scope(
            getattr(args, "scope_primary", None),
            getattr(args, "scope_secondary", None), adapter_kind,
        )
        config, config_path, config_sha256, adapter_id, capability_sha256 = \
            _load_adapter(
                adapter_kind, args.config, args.expected_config_sha256, scope
            )
        adapter_runtime.revalidate_artifacts(config, "Adapter conformance")
        optional_environment = config.get("optionalEnvironmentVariables", [])
        adapter_runtime.validate_environment_policy(
            config["environmentVariables"], optional=optional_environment,
            label="Adapter conformance",
        )
        isolated = adapter_runtime.isolated_environment(
            config["environmentVariables"], optional=optional_environment,
            require_required=False, label="Adapter conformance",
        )
        if any(name not in {"SystemRoot", "WINDIR"}
               and name not in config["environmentVariables"]
               and name not in optional_environment for name in isolated):
            raise ValueError("Adapter conformance environment escaped policy")
        second = _load_adapter(
            adapter_kind, config_path, config_sha256, scope
        )
        if (second[0] != config or second[1] != config_path
                or second[2] != config_sha256 or second[3] != adapter_id
                or second[4] != capability_sha256):
            raise ValueError("Adapter conformance replay identity changed")
        changed_sha256 = (
            ("0" if config_sha256[0] != "0" else "1")
            + config_sha256[1:]
        )
        try:
            _load_adapter(adapter_kind, config_path, changed_sha256, scope)
        except (OSError, UnicodeError, ValueError, RuntimeError,
                json.JSONDecodeError):
            pass
        else:
            raise ValueError("Adapter conformance accepted a wrong config pin")
        if package_tool.sha256_file(config_path) != config_sha256:
            raise ValueError("Adapter conformance config changed after replay")
        protocol = {
            "major": config["protocolMajor"],
            "minimumMinor": config["minimumProtocolMinor"],
        }
        required_capabilities = list(config["requiredCapabilities"])
        binding = {
            "certificationLevel": CERTIFICATION_LEVEL,
            "checkSetVersion": CHECK_SET_VERSION,
            "adapterKind": adapter_kind, "adapterId": adapter_id,
            "configSha256": config_sha256, "scope": scope,
            "protocol": protocol,
            "requiredCapabilities": required_capabilities,
            "capabilityManifestSha256": capability_sha256,
        }
        conformance_id = package_tool.sha256_bytes(
            package_tool.json_bytes(binding)
        )
        checks = {
            "adapter-identity-bound": {
                "adapterKind": adapter_kind, "adapterId": adapter_id,
            },
            "artifact-pins-revalidated": {
                "count": 1 + len(config["artifactPins"]),
            },
            "capability-negotiated": {
                "capabilityManifestSha256": capability_sha256,
                "requiredCapabilities": required_capabilities,
            },
            "capability-replay-stable": {
                "first": capability_sha256, "second": second[4],
            },
            "config-pin-enforced": {
                "configSha256": config_sha256, "wrongPinRejected": True,
            },
            "config-revalidated": {
                "before": config_sha256,
                "after": package_tool.sha256_file(config_path),
            },
            "environment-confined": {
                "requiredCount": len(config["environmentVariables"]),
                "optionalCount": len(optional_environment),
            },
            "evidence-redacted": {
                "configPathExcluded": True, "configContentExcluded": True,
                "environmentValuesExcluded": True,
            },
            "process-policy-bounded": {
                "timeoutSeconds": config["timeoutSeconds"],
                "maxResponseBytes": config["maxResponseBytes"],
            },
        }
        report = {
            "schemaVersion": 1, "product": EVIDENCE_PRODUCT,
            "passed": True, "certificationLevel": CERTIFICATION_LEVEL,
            "checkSetVersion": CHECK_SET_VERSION,
            "conformanceId": conformance_id,
            "adapterKind": adapter_kind, "adapterId": adapter_id,
            "configSchemaVersion": config["schemaVersion"],
            "configSha256": config_sha256, "scope": scope,
            "protocol": protocol,
            "requiredCapabilities": required_capabilities,
            "capabilityManifestSha256": capability_sha256,
            "checks": [_check(check_id, checks[check_id])
                       for check_id in CHECK_IDS],
            "certifiedAt": registry_tool.utc_time(None),
            "reportSha256": "0" * 64,
        }
        serialized = package_tool.json_bytes(report)
        if str(config_path).encode() in serialized:
            raise ValueError("Adapter conformance evidence exposes a local path")
        report["reportSha256"] = _report_digest(report)
        validate_evidence(report)
        package_tool.write_json(Path(args.report).resolve(), report)
        print(
            "PDR_ADAPTER_CONFORMANCE_PASS "
            f"kind={adapter_kind} adapter={adapter_id} "
            f"conformance={conformance_id}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CONFORMANCE_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--adapter-kind", choices=sorted(SUPPORTED_KINDS),
                        required=True)
    result.add_argument("--config", required=True)
    result.add_argument("--expected-config-sha256", required=True)
    result.add_argument("--scope-primary")
    result.add_argument("--scope-secondary")
    result.add_argument("--report", required=True)
    return result


def main() -> int:
    return execute_command(parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
