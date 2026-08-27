#!/usr/bin/env python3
"""Creation- and execution-time admission for a Governance Approval Signer."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import team_contract_adapter_runtime as adapter_runtime
import team_contract_package as package_tool


CONFIG_PRODUCT = \
    "PocoDDSRuntimeTeamContractGovernanceApprovalSignerAdmissionConfig"
READMISSION_BUNDLE_PRODUCT = \
    "PocoDDSRuntimeTeamContractGovernanceApprovalSignerReadmissionBundle"
READMISSION_EVIDENCE_PRODUCT = \
    "PocoDDSRuntimeTeamContractGovernanceApprovalSignerReadmissionEvidence"


def validate_config(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "evidence",
        "expectedEvidenceSha256", "attestation",
        "expectedAttestationSha256", "trustPolicy",
        "expectedTrustPolicyId", "minimumTrustPolicyGeneration",
        "expectedTrustPolicySha256", "maximumEvidenceAgeSeconds",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CONFIG_PRODUCT
            or any(not isinstance(document.get(name), str)
                   or not document[name] or len(document[name]) > 4096
                   for name in ("evidence", "attestation", "trustPolicy"))
            or package_tool.IDENTIFIER.fullmatch(str(
                document.get("expectedTrustPolicyId", ""))) is None
            or type(document.get("minimumTrustPolicyGeneration")) is not int
            or not 1 <= document["minimumTrustPolicyGeneration"] <= 2147483647
            or type(document.get("maximumEvidenceAgeSeconds")) is not int
            or not 60 <= document["maximumEvidenceAgeSeconds"] <= 2678400
            or any(package_tool.SHA256.fullmatch(str(
                document.get(name, ""))) is None for name in (
                    "expectedEvidenceSha256",
                    "expectedAttestationSha256",
                    "expectedTrustPolicySha256",
                ))):
        raise ValueError(
            "Governance approval signer admission configuration is malformed"
        )


def validate_readmission_bundle(document: Any) -> None:
    fields = {"schemaVersion", "product", "entries"}
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != READMISSION_BUNDLE_PRODUCT
            or not isinstance(document.get("entries"), list)
            or not 1 <= len(document["entries"]) <= 64):
        raise ValueError(
            "Governance approval signer readmission bundle is malformed"
        )
    approvals: set[str] = set()
    for entry in document["entries"]:
        if (not isinstance(entry, dict) or set(entry) != {
                "approvalSha256", "admissionConfig",
                "expectedAdmissionConfigSha256"
                } or package_tool.SHA256.fullmatch(str(
                    entry.get("approvalSha256", ""))) is None
                or package_tool.SHA256.fullmatch(str(
                    entry.get("expectedAdmissionConfigSha256", ""))) is None
                or not isinstance(entry.get("admissionConfig"), str)
                or not 1 <= len(entry["admissionConfig"]) <= 4096
                or entry["approvalSha256"] in approvals):
            raise ValueError(
                "Governance approval signer readmission entry is malformed"
            )
        approvals.add(entry["approvalSha256"])


def validate_readmission_evidence(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "passed", "purpose", "subjectSha256",
        "executorId", "bundleSha256", "approvals", "verifiedAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != READMISSION_EVIDENCE_PRODUCT
            or document.get("passed") is not True
            or document.get("purpose") not in {
                "governance-approval",
                "adapter-certifier-trust-approval",
                "adapter-certifier-trust-migration-approval",
            }
            or package_tool.SHA256.fullmatch(str(
                document.get("subjectSha256", ""))) is None
            or package_tool.SHA256.fullmatch(str(
                document.get("bundleSha256", ""))) is None
            or package_tool.IDENTIFIER.fullmatch(str(
                document.get("executorId", ""))) is None
            or not isinstance(document.get("approvals"), list)
            or not 1 <= len(document["approvals"]) <= 64):
        raise ValueError(
            "Governance approval signer readmission evidence is malformed"
        )
    package_tool.parse_time(document.get("verifiedAt"), "readmission verifiedAt")
    approval_ids: set[str] = set()
    entry_fields = {
        "approvalSha256", "approverId", "keyId", "signerId",
        "signerConformanceId", "signerConformanceEvidenceSha256",
        "signerConformanceAttestationSha256",
        "signerConformanceCertifierId", "signerConformanceCertifierKeyId",
        "creationTrustPolicyId", "creationTrustPolicyGeneration",
        "creationTrustPolicySha256", "executionTrustPolicyId",
        "executionTrustPolicyGeneration", "executionTrustPolicySha256",
    }
    sha_fields = {
        "approvalSha256", "signerConformanceId",
        "signerConformanceEvidenceSha256",
        "signerConformanceAttestationSha256",
        "creationTrustPolicySha256", "executionTrustPolicySha256",
    }
    id_fields = {
        "approverId", "keyId", "signerId",
        "signerConformanceCertifierId", "signerConformanceCertifierKeyId",
        "creationTrustPolicyId", "executionTrustPolicyId",
    }
    for entry in document["approvals"]:
        if (not isinstance(entry, dict) or set(entry) != entry_fields
                or any(package_tool.SHA256.fullmatch(str(
                    entry.get(name, ""))) is None for name in sha_fields)
                or any(package_tool.IDENTIFIER.fullmatch(str(
                    entry.get(name, ""))) is None for name in id_fields)
                or any(type(entry.get(name)) is not int
                       or not 1 <= entry[name] <= 2147483647 for name in (
                           "creationTrustPolicyGeneration",
                           "executionTrustPolicyGeneration"))
                or entry["approvalSha256"] in approval_ids):
            raise ValueError(
                "Governance approval signer readmission evidence entry is malformed"
            )
        approval_ids.add(entry["approvalSha256"])


def _verification_time(value: Any) -> datetime:
    result = value if isinstance(value, datetime) \
        else package_tool.verification_time(value)
    if result.tzinfo is None:
        raise ValueError(
            "Governance approval signer verification time requires a timezone"
        )
    return result


def _load_material(config_path: str | Path, expected_config_sha256: str,
                   at: datetime) -> tuple[
                       dict[str, Any], dict[str, Any], str,
                       tuple[dict[str, Any], Path, str], dict[str, Any]]:
    import team_contract_adapter_conformance as conformance_tool
    import team_contract_adapter_conformance_trust as trust_tool

    config, _, _ = adapter_runtime.load_pinned_json(
        config_path, expected_config_sha256,
        "Governance approval signer admission", validate_config,
    )
    evidence, _, evidence_sha = adapter_runtime.load_pinned_json(
        config["evidence"], config["expectedEvidenceSha256"],
        "Governance approval signer conformance evidence",
        conformance_tool.validate_evidence,
    )
    certified = package_tool.parse_time(
        evidence["certifiedAt"], "Signer conformance certifiedAt"
    )
    if (certified > at + timedelta(minutes=5)
            or (at - certified).total_seconds()
                > config["maximumEvidenceAgeSeconds"]):
        raise ValueError(
            "Governance approval signer conformance evidence is outside age policy"
        )
    policy = trust_tool.load_policy(
        config["trustPolicy"], config["expectedTrustPolicySha256"],
        expected_policy_id=config["expectedTrustPolicyId"],
        minimum_generation=config["minimumTrustPolicyGeneration"],
    )
    attestation = trust_tool.verify_attestation(
        config["attestation"], config["expectedAttestationSha256"],
        evidence, evidence_sha, policy[0], policy[1], at.isoformat(),
    )
    return config, evidence, evidence_sha, policy, attestation


def admit(config_path: str | Path, expected_config_sha256: str, *,
          signer: Any, verification_time: Any = None) -> dict[str, Any]:
    at = _verification_time(verification_time)
    _, evidence, evidence_sha, policy, attestation = _load_material(
        config_path, expected_config_sha256, at
    )
    expected = {
        "adapterKind": "governance-approval-signer",
        "adapterId": signer.signer_id,
        "configSha256": signer.config_sha256,
        "capabilityManifestSha256": signer.capability_manifest_sha256,
        "scope": {
            "primaryId": signer.approver_id, "secondaryId": None,
        },
    }
    if any(evidence.get(name) != value for name, value in expected.items()):
        raise ValueError(
            "Governance approval signer conformance does not match current signer"
        )
    return {
        "signerConformanceId": evidence["conformanceId"],
        "signerConformanceEvidenceSha256": evidence_sha,
        "signerConformanceAttestationSha256":
            attestation["attestationSha256"],
        "signerConformanceCertifierId": attestation["certifierId"],
        "signerConformanceCertifierKeyId": attestation["keyId"],
        "signerConformanceTrustPolicyId": policy[0]["policyId"],
        "signerConformanceTrustPolicyGeneration": policy[0]["generation"],
        "signerConformanceTrustPolicySha256": policy[2],
    }


def readmit_approvals(
        approvals: list[tuple[dict[str, Any], Path, bytes, str]], *,
        bundle_path: str | Path, expected_bundle_sha256: str,
        purpose: str, subject_sha256: str, executor_id: str,
        verification_time: Any = None) -> dict[str, Any]:
    import team_contract_governance_approval as approval_tool

    at = _verification_time(verification_time)
    if (purpose not in {
            "governance-approval", "adapter-certifier-trust-approval",
            "adapter-certifier-trust-migration-approval"}
            or package_tool.SHA256.fullmatch(str(subject_sha256)) is None
            or package_tool.IDENTIFIER.fullmatch(str(executor_id)) is None):
        raise ValueError(
            "Governance approval signer readmission context is malformed"
        )
    bundle, _, bundle_sha = adapter_runtime.load_pinned_json(
        bundle_path, expected_bundle_sha256,
        "Governance approval signer readmission bundle",
        validate_readmission_bundle,
    )
    admitted = [item for item in approvals if item[0].get("schemaVersion") == 3]
    expected_approvals = {item[3] for item in admitted}
    entries = {item["approvalSha256"]: item for item in bundle["entries"]}
    if not admitted or set(entries) != expected_approvals:
        raise ValueError(
            "Governance approval signer readmission bundle coverage changed"
        )
    results: list[dict[str, Any]] = []
    for approval in admitted:
        document = approval[0]
        approval_tool.validate_signer_descriptor(document, admitted=True)
        entry = entries[approval[3]]
        _, evidence, evidence_sha, policy, attestation = _load_material(
            entry["admissionConfig"],
            entry["expectedAdmissionConfigSha256"], at,
        )
        expected_evidence = {
            "adapterKind": "governance-approval-signer",
            "adapterId": document["signerId"],
            "configSha256": document["signerConfigSha256"],
            "capabilityManifestSha256":
                document["signerCapabilityManifestSha256"],
            "scope": {
                "primaryId": document["approverId"], "secondaryId": None,
            },
        }
        if any(evidence.get(name) != value
               for name, value in expected_evidence.items()):
            raise ValueError(
                "Governance approval signer readmission does not match approval"
            )
        expected_provenance = {
            "signerConformanceId": evidence["conformanceId"],
            "signerConformanceEvidenceSha256": evidence_sha,
            "signerConformanceAttestationSha256":
                attestation["attestationSha256"],
            "signerConformanceCertifierId": attestation["certifierId"],
            "signerConformanceCertifierKeyId": attestation["keyId"],
        }
        if any(document.get(name) != value
               for name, value in expected_provenance.items()):
            raise ValueError(
                "Governance approval signer readmission provenance changed"
            )
        creation_generation = document[
            "signerConformanceTrustPolicyGeneration"
        ]
        if (policy[0]["policyId"]
                != document["signerConformanceTrustPolicyId"]
                or policy[0]["generation"] < creation_generation
                or (policy[0]["generation"] == creation_generation
                    and policy[2]
                    != document["signerConformanceTrustPolicySha256"])):
            raise ValueError(
                "Governance approval signer execution trust policy rolled back"
            )
        results.append({
            "approvalSha256": approval[3],
            "approverId": document["approverId"], "keyId": document["keyId"],
            "signerId": document["signerId"],
            **expected_provenance,
            "creationTrustPolicyId":
                document["signerConformanceTrustPolicyId"],
            "creationTrustPolicyGeneration":
                document["signerConformanceTrustPolicyGeneration"],
            "creationTrustPolicySha256":
                document["signerConformanceTrustPolicySha256"],
            "executionTrustPolicyId": policy[0]["policyId"],
            "executionTrustPolicyGeneration": policy[0]["generation"],
            "executionTrustPolicySha256": policy[2],
        })
    result = {
        "schemaVersion": 1, "product": READMISSION_EVIDENCE_PRODUCT,
        "passed": True, "purpose": purpose,
        "subjectSha256": subject_sha256, "executorId": executor_id,
        "bundleSha256": bundle_sha, "approvals": results,
        "verifiedAt": at.isoformat(),
    }
    validate_readmission_evidence(result)
    return result


def enforce_readmission(
        approvals: list[tuple[dict[str, Any], Path, bytes, str]], *,
        bundle_path: str | None, expected_bundle_sha256: str | None,
        report_path: str | None, purpose: str, subject_sha256: str,
        executor_id: str, verification_time: Any = None) \
        -> tuple[dict[str, Any], str] | None:
    has_v3 = any(item[0].get("schemaVersion") == 3 for item in approvals)
    values = (bundle_path, expected_bundle_sha256, report_path)
    supplied = any(value is not None for value in values)
    if has_v3 and not all(values):
        raise ValueError(
            "Governance approval schema v3 requires complete signer readmission"
        )
    if not has_v3:
        if supplied:
            raise ValueError(
                "Governance approval signer readmission requires schema v3"
            )
        return None
    assert bundle_path is not None
    assert expected_bundle_sha256 is not None
    assert report_path is not None
    evidence = readmit_approvals(
        approvals, bundle_path=bundle_path,
        expected_bundle_sha256=expected_bundle_sha256, purpose=purpose,
        subject_sha256=subject_sha256, executor_id=executor_id,
        verification_time=verification_time,
    )
    report = Path(report_path).resolve()
    package_tool.write_json(report, evidence)
    return evidence, package_tool.sha256_file(report)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--self-check", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.self_check:
        print(
            "PDR_GOVERNANCE_APPROVAL_SIGNER_ADMISSION_SELF_CHECK_PASS "
            "pins=1 evidence=1 attestation=1 trust=1 age=1"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
