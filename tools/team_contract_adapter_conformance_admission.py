#!/usr/bin/env python3
"""Load and enforce a pinned Adapter conformance admission bundle."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import team_contract_adapter_runtime as adapter_runtime
import team_contract_package as package_tool
import team_contract_registry as registry_tool


BUNDLE_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterConformanceAdmissionBundle"
POLICY_LEVEL = "integration-readiness"
POLICY_CHECK_SET = "1.0.0"
IDENTITY_FIELDS = {
    "adapter-config-resolver": "resolverId", "artifact-store": "storeId",
    "control-authorizer": "authorizerId", "fleet-executor": "executorId",
    "registry-leader-backend": "backendId", "wave-gate": "gateId",
}
REQUIRED_KINDS = sorted(IDENTITY_FIELDS)
REQUIRED_CHECKS = [
    "adapter-identity-bound", "artifact-pins-revalidated",
    "capability-negotiated", "capability-replay-stable",
    "config-pin-enforced", "config-revalidated", "environment-confined",
    "evidence-redacted", "process-policy-bounded",
]


def _validate_evidence(document: Any) -> None:
    # Lazy import avoids the conformance -> Fleet -> admission import cycle.
    import team_contract_adapter_conformance as conformance_tool
    conformance_tool.validate_evidence(document)


def validate_summary(document: Any) -> None:
    base_fields = {
        "admissionId", "policyId", "coordinatorId", "bundleSha256",
        "entries", "admittedAt",
    }
    signed_fields = base_fields | {
        "trustPolicyId", "trustPolicyGeneration", "trustPolicySha256",
    }
    signed = isinstance(document, dict) and set(document) == signed_fields
    if (not isinstance(document, dict)
            or set(document) not in (base_fields, signed_fields)
            or any(package_tool.IDENTIFIER.fullmatch(str(
                document.get(name, ""))) is None
                for name in ("policyId", "coordinatorId"))
            or any(package_tool.SHA256.fullmatch(str(
                document.get(name, ""))) is None
                for name in ("admissionId", "bundleSha256"))
            or not isinstance(document.get("entries"), list)
            or len(document["entries"]) != len(REQUIRED_KINDS)):
        raise ValueError("Adapter conformance admission summary is malformed")
    if signed and (
            package_tool.IDENTIFIER.fullmatch(str(
                document.get("trustPolicyId", ""))) is None
            or type(document.get("trustPolicyGeneration")) is not int
            or document["trustPolicyGeneration"] < 1
            or package_tool.SHA256.fullmatch(str(
                document.get("trustPolicySha256", ""))) is None):
        raise ValueError(
            "Adapter conformance admission trust summary is malformed"
        )
    kinds = []
    for entry in document["entries"]:
        base_entry = {
                "adapterKind", "adapterId", "configSha256",
                "capabilityManifestSha256", "conformanceId",
                "evidenceSha256",
        }
        signed_entry = base_entry | {
            "attestationSha256", "certifierId", "keyId",
        }
        if (not isinstance(entry, dict)
                or set(entry) != (signed_entry if signed else base_entry)
                or entry.get("adapterKind") not in REQUIRED_KINDS
                or package_tool.IDENTIFIER.fullmatch(str(
                    entry.get("adapterId", ""))) is None
                or any(package_tool.SHA256.fullmatch(str(
                    entry.get(name, ""))) is None for name in (
                        "configSha256", "capabilityManifestSha256",
                        "conformanceId", "evidenceSha256",
                    ))):
            raise ValueError(
                "Adapter conformance admission summary entry is malformed"
            )
        if signed and (
                any(package_tool.IDENTIFIER.fullmatch(str(
                    entry.get(name, ""))) is None
                    for name in ("certifierId", "keyId"))
                or package_tool.SHA256.fullmatch(str(
                    entry.get("attestationSha256", ""))) is None):
            raise ValueError(
                "Adapter conformance admission signer entry is malformed"
            )
        kinds.append(entry["adapterKind"])
    if kinds != REQUIRED_KINDS:
        raise ValueError("Adapter conformance admission summary is incomplete")
    package_tool.parse_time(document.get("admittedAt"), "admittedAt")
    binding = {
        "policyId": document["policyId"],
        "coordinatorId": document["coordinatorId"],
        "bundleSha256": document["bundleSha256"],
        "entries": document["entries"],
    }
    if signed:
        binding.update({
            "trustPolicyId": document["trustPolicyId"],
            "trustPolicyGeneration": document["trustPolicyGeneration"],
            "trustPolicySha256": document["trustPolicySha256"],
        })
    if document["admissionId"] != package_tool.sha256_bytes(
            package_tool.json_bytes(binding)):
        raise ValueError("Adapter conformance admission identity changed")


def validate_policy(document: Any) -> None:
    fields = {
        "policyId", "certificationLevel", "checkSetVersion",
        "maximumEvidenceAgeSeconds", "requiredAdapterKinds",
        "requiredChecks",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or package_tool.IDENTIFIER.fullmatch(str(
                document.get("policyId", ""))) is None
            or document.get("certificationLevel") != POLICY_LEVEL
            or document.get("checkSetVersion") != POLICY_CHECK_SET
            or type(document.get("maximumEvidenceAgeSeconds")) is not int
            or not 60 <= document["maximumEvidenceAgeSeconds"] <= 2678400
            or document.get("requiredAdapterKinds") != REQUIRED_KINDS
            or document.get("requiredChecks") != REQUIRED_CHECKS):
        raise ValueError("Adapter conformance admission policy is malformed")


def validate_trust_requirement(document: Any) -> None:
    if (not isinstance(document, dict) or set(document) != {
            "policyId", "minimumGeneration"
            } or package_tool.IDENTIFIER.fullmatch(str(
                document.get("policyId", ""))) is None
            or type(document.get("minimumGeneration")) is not int
            or not 1 <= document["minimumGeneration"] <= 2147483647):
        raise ValueError(
            "Adapter conformance trust requirement is malformed"
        )


def validate_bundle(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "bundleId", "rolloutId", "catalogId",
        "entries",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") not in {1, 2}
            or document.get("product") != BUNDLE_PRODUCT
            or any(package_tool.IDENTIFIER.fullmatch(str(
                document.get(name, ""))) is None
                for name in ("bundleId", "rolloutId", "catalogId"))
            or not isinstance(document.get("entries"), list)
            or len(document["entries"]) != len(REQUIRED_KINDS)):
        raise ValueError("Adapter conformance admission bundle is malformed")
    kinds = []
    for entry in document["entries"]:
        expected_fields = {
            "adapterKind", "evidencePath", "evidenceSha256"
        }
        if document["schemaVersion"] == 2:
            expected_fields |= {"attestationPath", "attestationSha256"}
        if (not isinstance(entry, dict) or set(entry) != expected_fields
                or entry.get("adapterKind") not in REQUIRED_KINDS
                or not isinstance(entry.get("evidencePath"), str)
                or not Path(entry["evidencePath"]).is_absolute()
                or package_tool.SHA256.fullmatch(str(
                    entry.get("evidenceSha256", ""))) is None):
            raise ValueError(
                "Adapter conformance admission bundle entry is malformed"
            )
        if document["schemaVersion"] == 2 and (
                not isinstance(entry.get("attestationPath"), str)
                or not Path(entry["attestationPath"]).is_absolute()
                or package_tool.SHA256.fullmatch(str(
                    entry.get("attestationSha256", ""))) is None):
            raise ValueError(
                "Adapter conformance attestation bundle entry is malformed"
            )
        kinds.append(entry["adapterKind"])
    if kinds != REQUIRED_KINDS:
        raise ValueError(
            "Adapter conformance admission bundle kinds are incomplete"
        )


class Admission:
    """Pinned, policy-checked evidence used by one Fleet invocation."""

    def __init__(self, bundle_path: str | Path, expected_sha256: str,
                 policy: dict[str, Any], *, rollout_id: str, catalog_id: str,
                 at: datetime | None = None,
                 trust_policy_path: str | Path | None = None,
                 expected_trust_policy_sha256: str | None = None,
                 expected_trust_policy_id: str | None = None,
                 minimum_trust_policy_generation: int | None = None):
        validate_policy(policy)
        bundle, path, digest = adapter_runtime.load_pinned_json(
            bundle_path, expected_sha256,
            "Adapter conformance admission bundle", validate_bundle,
        )
        if (bundle["rolloutId"] != rollout_id
                or bundle["catalogId"] != catalog_id):
            raise ValueError(
                "Adapter conformance admission bundle scope changed"
            )
        self.bundle = bundle
        self.bundle_path = path
        self.bundle_sha256 = digest
        self.policy = policy
        self._evidence: dict[str, dict[str, Any]] = {}
        self._evidence_sha: dict[str, str] = {}
        self._prechecked: set[str] = set()
        self._postchecked: set[str] = set()
        self._trust: dict[str, dict[str, str]] = {}
        self.trust_policy: dict[str, Any] | None = None
        self.trust_policy_sha256: str | None = None
        self.trust_policy_path: Path | None = None
        trust_values = (
            trust_policy_path, expected_trust_policy_sha256,
            expected_trust_policy_id, minimum_trust_policy_generation,
        )
        signed = bundle["schemaVersion"] == 2
        if signed != all(value is not None for value in trust_values):
            raise ValueError(
                "signed Adapter admission requires a complete trust policy"
            )
        if signed:
            import team_contract_adapter_conformance_trust as trust_tool
            assert expected_trust_policy_sha256 is not None
            assert expected_trust_policy_id is not None
            assert minimum_trust_policy_generation is not None
            self.trust_policy, self.trust_policy_path, \
                self.trust_policy_sha256 = trust_tool.load_policy(
                    trust_policy_path, expected_trust_policy_sha256,
                    expected_policy_id=expected_trust_policy_id,
                    minimum_generation=minimum_trust_policy_generation,
                )
        now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        for entry in bundle["entries"]:
            evidence, _, evidence_sha = adapter_runtime.load_pinned_json(
                entry["evidencePath"], entry["evidenceSha256"],
                f"{entry['adapterKind']} conformance evidence",
                _validate_evidence,
            )
            kind = entry["adapterKind"]
            if evidence["adapterKind"] != kind:
                raise ValueError(
                    "Adapter conformance evidence kind changed"
                )
            certified = package_tool.parse_time(
                evidence["certifiedAt"], "certifiedAt"
            )
            age = (now - certified).total_seconds()
            if age < -300 or age > policy["maximumEvidenceAgeSeconds"]:
                raise ValueError(
                    f"{kind} conformance evidence is outside policy age"
                )
            if (evidence["certificationLevel"]
                    != policy["certificationLevel"]
                    or evidence["checkSetVersion"]
                    != policy["checkSetVersion"]
                    or [item["checkId"] for item in evidence["checks"]]
                    != policy["requiredChecks"]):
                raise ValueError(
                    f"{kind} conformance evidence violates policy"
                )
            self._evidence[kind] = evidence
            self._evidence_sha[kind] = evidence_sha
            if signed:
                assert self.trust_policy is not None
                assert self.trust_policy_path is not None
                self._trust[kind] = trust_tool.verify_attestation(
                    entry["attestationPath"], entry["attestationSha256"],
                    evidence, evidence_sha, self.trust_policy,
                    self.trust_policy_path, now.isoformat(),
                )

    def precheck(self, kind: str, config: dict[str, Any], config_sha256: str,
                 *, adapter_id: str, scope: dict[str, str | None]) -> None:
        evidence = self._evidence.get(kind)
        identity_field = IDENTITY_FIELDS.get(kind)
        if (evidence is None or identity_field is None
                or config.get(identity_field) != adapter_id
                or evidence["adapterId"] != adapter_id
                or evidence["configSchemaVersion"] != config.get("schemaVersion")
                or evidence["configSha256"] != config_sha256
                or evidence["scope"] != scope
                or evidence["protocol"] != {
                    "major": config.get("protocolMajor"),
                    "minimumMinor": config.get("minimumProtocolMinor"),
                }
                or evidence["requiredCapabilities"]
                    != config.get("requiredCapabilities")):
            raise ValueError(
                f"{kind} conformance evidence does not bind active config"
            )
        self._prechecked.add(kind)

    def postcheck(self, kind: str, capability_sha256: str) -> None:
        if kind not in self._prechecked:
            raise ValueError(f"{kind} conformance config was not admitted")
        if self._evidence[kind]["capabilityManifestSha256"] \
                != capability_sha256:
            raise ValueError(
                f"{kind} conformance capability identity changed"
            )
        self._postchecked.add(kind)

    def summary(self, coordinator_id: str) -> dict[str, Any]:
        if self._postchecked != set(REQUIRED_KINDS):
            missing = sorted(set(REQUIRED_KINDS) - self._postchecked)
            raise ValueError(
                "Adapter conformance admission is incomplete: "
                + ", ".join(missing)
            )
        entries = [{
            "adapterKind": kind,
            "adapterId": self._evidence[kind]["adapterId"],
            "configSha256": self._evidence[kind]["configSha256"],
            "capabilityManifestSha256":
                self._evidence[kind]["capabilityManifestSha256"],
            "conformanceId": self._evidence[kind]["conformanceId"],
            "evidenceSha256": self._evidence_sha[kind],
        } for kind in REQUIRED_KINDS]
        if self.trust_policy is not None:
            for entry in entries:
                trust = self._trust[entry["adapterKind"]]
                entry.update({
                    "attestationSha256": trust["attestationSha256"],
                    "certifierId": trust["certifierId"],
                    "keyId": trust["keyId"],
                })
        binding = {
            "policyId": self.policy["policyId"],
            "coordinatorId": coordinator_id,
            "bundleSha256": self.bundle_sha256,
            "entries": entries,
        }
        if self.trust_policy is not None:
            assert self.trust_policy_sha256 is not None
            binding.update({
                "trustPolicyId": self.trust_policy["policyId"],
                "trustPolicyGeneration": self.trust_policy["generation"],
                "trustPolicySha256": self.trust_policy_sha256,
            })
        return {
            "admissionId": package_tool.sha256_bytes(
                package_tool.json_bytes(binding)
            ),
            **binding,
            "admittedAt": registry_tool.utc_time(None),
        }


def create_command(args: argparse.Namespace) -> int:
    try:
        entries = []
        attestation_items = getattr(args, "attestation", []) or []
        attestations = dict(attestation_items)
        if len(attestations) != len(attestation_items):
            raise ValueError("attestation Adapter kinds must be unique")
        for kind, path_value in args.evidence:
            path = Path(path_value)
            if not path.is_absolute() or path.is_symlink() or not path.is_file():
                raise ValueError("evidence must be an absolute non-link file")
            path = path.resolve()
            evidence = json.loads(path.read_bytes())
            _validate_evidence(evidence)
            if evidence["adapterKind"] != kind:
                raise ValueError("evidence Adapter kind changed")
            entries.append({
                "adapterKind": kind, "evidencePath": str(path),
                "evidenceSha256": package_tool.sha256_file(path),
            })
            if attestations:
                attestation_path = Path(attestations.get(kind, ""))
                if (not attestation_path.is_absolute()
                        or attestation_path.is_symlink()
                        or not attestation_path.is_file()):
                    raise ValueError(
                        "attestation must be an absolute non-link file"
                    )
                attestation_path = attestation_path.resolve()
                entries[-1].update({
                    "attestationPath": str(attestation_path),
                    "attestationSha256":
                        package_tool.sha256_file(attestation_path),
                })
        entries.sort(key=lambda item: item["adapterKind"])
        document = {
            "schemaVersion": 2 if attestations else 1,
            "product": BUNDLE_PRODUCT,
            "bundleId": args.bundle_id, "rolloutId": args.rollout_id,
            "catalogId": args.catalog_id, "entries": entries,
        }
        validate_bundle(document)
        output = Path(args.output).resolve()
        package_tool.write_json(output, document)
        print(
            "PDR_ADAPTER_CONFORMANCE_ADMISSION_CREATE_PASS "
            f"bundle={args.bundle_id} sha256={package_tool.sha256_file(output)}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CONFORMANCE_ADMISSION_CREATE_ERROR: {error}",
              file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    create = commands.add_parser("create")
    create.add_argument("--bundle-id", required=True)
    create.add_argument("--rollout-id", required=True)
    create.add_argument("--catalog-id", required=True)
    create.add_argument("--evidence", action="append", nargs=2,
                        metavar=("KIND", "PATH"), required=True)
    create.add_argument("--attestation", action="append", nargs=2,
                        metavar=("KIND", "PATH"))
    create.add_argument("--output", required=True)
    create.set_defaults(handler=create_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
