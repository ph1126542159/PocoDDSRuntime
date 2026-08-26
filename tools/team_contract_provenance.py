#!/usr/bin/env python3
"""Sign trusted CI execution and externally anchor team-contract Registry state."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

import team_contract_impact as impact_tool
import team_contract_impact_gate as gate_tool
import team_contract_package as package_tool
import team_contract_registry as registry_tool


RUNNER_POLICY_PRODUCT = "PocoDDSRuntimeTeamContractRunnerTrustPolicy"
RUNNER_ATTESTATION_PRODUCT = "PocoDDSRuntimeTeamContractRunnerAttestation"
GATE_AUTH_POLICY_PRODUCT = "PocoDDSRuntimeTeamContractGateAuthorizationPolicy"
GATE_AUTH_PRODUCT = "PocoDDSRuntimeTeamContractGateAuthorization"
GATE_AUTH_VERIFICATION_PRODUCT = "PocoDDSRuntimeTeamContractGateAuthorizationVerification"
ANCHOR_POLICY_PRODUCT = "PocoDDSRuntimeTeamContractRegistryAnchorPolicy"
ANCHOR_PRODUCT = "PocoDDSRuntimeTeamContractRegistryAnchor"
ANCHOR_VERIFICATION_PRODUCT = "PocoDDSRuntimeTeamContractRegistryAnchorVerification"
MAX_LIFETIME = 86400
REPOSITORY = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def canonical_payload(document: dict[str, Any]) -> bytes:
    return package_tool.canonical_bytes({
        key: value for key, value in document.items() if key != "signature"
    })


def private_key(args: argparse.Namespace) -> Any:
    key_value = os.environ.get(args.private_key_environment)
    if not key_value:
        raise ValueError("private key path environment is unset")
    key_path = package_tool.resolved_path(key_value, "provenance private key")
    passphrase = None
    if args.private_key_passphrase_environment:
        value = os.environ.get(args.private_key_passphrase_environment)
        if value is None:
            raise ValueError("private key passphrase environment is unset")
        passphrase = value.encode("utf-8")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as error:
        raise ValueError("signed provenance requires the cryptography package") from error
    key = load_pem_private_key(key_path.read_bytes(), password=passphrase)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("provenance private key is not Ed25519")
    return key


def signature_bytes(value: Any) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as error:
        raise ValueError("provenance signature encoding is invalid") from error
    if len(decoded) != 64:
        raise ValueError("provenance Ed25519 signature length is invalid")
    return decoded


def load_policy(path: str | Path, expected_id: str, expected_sha: str,
                product: str, collection: str) -> tuple[dict[str, Any], Path, str]:
    policy_path = package_tool.resolved_path(path, "provenance trust policy")
    document, actual_sha = impact_tool.load_json(policy_path, "provenance trust policy")
    if (not package_tool.SHA256.fullmatch(str(expected_sha).lower())
            or actual_sha != str(expected_sha).lower()
            or document.get("schemaVersion") != 1
            or document.get("product") != product
            or document.get("policyId") != expected_id
            or not package_tool.IDENTIFIER.fullmatch(str(expected_id))
            or not isinstance(document.get(collection), list)
            or not document[collection]
            or not isinstance(document.get("revokedKeys"), list)):
        raise ValueError("provenance trust policy identity is not pinned or is malformed")
    return document, policy_path, actual_sha


def validate_revocations(document: dict[str, Any]) -> set[str]:
    revoked: set[str] = set()
    for item in document["revokedKeys"]:
        if (not isinstance(item, dict) or set(item) != {"keyId", "revokedAt", "reason"}
                or not package_tool.IDENTIFIER.fullmatch(str(item.get("keyId", "")))
                or not isinstance(item.get("reason"), str) or not item["reason"]
                or item["keyId"] in revoked):
            raise ValueError("provenance trust policy revocation is malformed")
        package_tool.parse_time(item["revokedAt"], "revokedAt")
        revoked.add(item["keyId"])
    return revoked


def validate_runner_policy(document: dict[str, Any]) -> None:
    if (set(document) != {
            "schemaVersion", "product", "policyId", "maxAttestationLifetimeSeconds",
            "allowedRunners", "revokedKeys"
        } or type(document.get("maxAttestationLifetimeSeconds")) is not int
            or not 60 <= document["maxAttestationLifetimeSeconds"] <= MAX_LIFETIME):
        raise ValueError("runner trust policy is malformed")
    fields = {
        "runnerId", "keyId", "algorithm", "publicKey", "publicKeySha256",
        "repositories", "workflows", "notBefore", "notAfter",
    }
    keys: set[str] = set()
    runners: set[str] = set()
    for item in document["allowedRunners"]:
        if (not isinstance(item, dict) or set(item) != fields
                or not package_tool.IDENTIFIER.fullmatch(str(item.get("runnerId", "")))
                or not package_tool.IDENTIFIER.fullmatch(str(item.get("keyId", "")))
                or item.get("algorithm") != "Ed25519"
                or not re.fullmatch(r"keys/[A-Za-z0-9._-]+\.pem",
                                    str(item.get("publicKey", "")))
                or not package_tool.SHA256.fullmatch(str(item.get("publicKeySha256", "")))
                or not isinstance(item.get("repositories"), list)
                or not item["repositories"] or len(item["repositories"]) != len(set(item["repositories"]))
                or any(not REPOSITORY.fullmatch(str(value)) for value in item["repositories"])
                or not isinstance(item.get("workflows"), list) or not item["workflows"]
                or len(item["workflows"]) != len(set(item["workflows"]))
                or any(not package_tool.IDENTIFIER.fullmatch(str(value))
                       for value in item["workflows"])
                or item["keyId"] in keys or item["runnerId"] in runners):
            raise ValueError("runner trust policy entry is malformed")
        if package_tool.parse_time(item["notBefore"], "notBefore") >= \
                package_tool.parse_time(item["notAfter"], "notAfter"):
            raise ValueError("runner trust policy validity window is reversed")
        keys.add(item["keyId"])
        runners.add(item["runnerId"])
    validate_revocations(document)


def execution_inputs(report_path: Path, evidence_path: Path,
                     junit_path: Path | None) -> tuple[dict[str, Any], str, dict[str, Any], str]:
    report, report_sha = gate_tool.impact_report(report_path)
    evidence, evidence_sha = impact_tool.load_json(
        package_tool.resolved_path(evidence_path, "impact execution evidence"),
        "impact execution evidence",
    )
    gate_tool.validate_evidence(evidence, report, report_sha, junit_path)
    return report, report_sha, evidence, evidence_sha


def validate_runner_attestation(document: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "operation", "runnerId", "repository",
        "sourceRevision", "workflow", "jobId", "runId", "issuedAt", "expiresAt",
        "impactReportSha256", "impactInputSetSha256", "candidateLockSha256",
        "executionEvidenceSha256", "junitSha256", "ctestExecutableSha256",
        "ctestCatalogSha256", "ctestCommandSha256", "keyId", "signature",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != RUNNER_ATTESTATION_PRODUCT
            or document.get("operation") != "team-contract-runner-attest"
            or not package_tool.IDENTIFIER.fullmatch(str(document.get("runnerId", "")))
            or not REPOSITORY.fullmatch(str(document.get("repository", "")))
            or not REVISION.fullmatch(str(document.get("sourceRevision", "")))
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(field, "")))
                   for field in ("workflow", "jobId", "runId", "keyId"))
            or any(not package_tool.SHA256.fullmatch(str(document.get(field, "")))
                   for field in ("impactReportSha256", "impactInputSetSha256",
                                 "candidateLockSha256", "executionEvidenceSha256",
                                 "ctestExecutableSha256", "ctestCatalogSha256",
                                 "ctestCommandSha256"))
            or (document.get("junitSha256") is not None
                and not package_tool.SHA256.fullmatch(str(document["junitSha256"])))):
        raise ValueError("runner attestation is malformed")
    issued = package_tool.parse_time(document["issuedAt"], "runner issuedAt")
    expires = package_tool.parse_time(document["expiresAt"], "runner expiresAt")
    if issued >= expires:
        raise ValueError("runner attestation validity window is reversed")
    signature_bytes(document.get("signature"))


def runner_attest_command(args: argparse.Namespace) -> int:
    try:
        if (not package_tool.IDENTIFIER.fullmatch(args.runner_id)
                or not REPOSITORY.fullmatch(args.repository)
                or not REVISION.fullmatch(args.source_revision.lower())
                or any(not package_tool.IDENTIFIER.fullmatch(value)
                       for value in (args.workflow, args.job_id, args.run_id, args.key_id))):
            raise ValueError("runner execution identity is invalid")
        if not 60 <= args.lifetime_seconds <= MAX_LIFETIME:
            raise ValueError("runner attestation lifetime is outside the supported range")
        requires_junit = evidence_requires_junit(Path(args.evidence))
        if requires_junit and not args.junit:
            raise ValueError("runner attestation requires the executed CTest JUnit evidence")
        report, report_sha, evidence, evidence_sha = execution_inputs(
            Path(args.report), Path(args.evidence),
            Path(args.junit) if requires_junit else None,
        )
        issued = package_tool.verification_time(args.issued_at)
        attestation = {
            "schemaVersion": 1,
            "product": RUNNER_ATTESTATION_PRODUCT,
            "operation": "team-contract-runner-attest",
            "runnerId": args.runner_id,
            "repository": args.repository,
            "sourceRevision": args.source_revision.lower(),
            "workflow": args.workflow,
            "jobId": args.job_id,
            "runId": args.run_id,
            "issuedAt": issued.isoformat(),
            "expiresAt": (issued + timedelta(seconds=args.lifetime_seconds)).isoformat(),
            "impactReportSha256": report_sha,
            "impactInputSetSha256": report["inputSetSha256"],
            "candidateLockSha256": report["candidateLockSha256"],
            "executionEvidenceSha256": evidence_sha,
            "junitSha256": evidence["junitSha256"],
            "ctestExecutableSha256": evidence["ctestExecutableSha256"],
            "ctestCatalogSha256": evidence["ctestCatalogSha256"],
            "ctestCommandSha256": evidence["ctestCommandSha256"],
            "keyId": args.key_id,
        }
        attestation["signature"] = base64.b64encode(
            private_key(args).sign(canonical_payload(attestation))
        ).decode("ascii")
        validate_runner_attestation(attestation)
        gate_tool.exclusive_json(Path(args.output), attestation)
        print(f"PDR_TEAM_CONTRACT_RUNNER_ATTEST_PASS runner={args.runner_id} "
              f"run={args.run_id}")
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_RUNNER_ATTEST_ERROR: {error}", file=sys.stderr)
        return 2


def evidence_requires_junit(path: Path) -> bool:
    evidence, _ = impact_tool.load_json(path, "impact execution evidence")
    return bool(evidence.get("requiredTestLabels"))


def verify_runner_signature(attestation_path: str | Path, policy_path: str | Path,
                            expected_policy_id: str, expected_policy_sha: str,
                            verification_time: str | None) \
        -> tuple[dict[str, Any], dict[str, Any]]:
    path = package_tool.resolved_path(attestation_path, "runner attestation")
    attestation, attestation_sha = impact_tool.load_json(path, "runner attestation")
    validate_runner_attestation(attestation)
    policy, policy_file, policy_sha = load_policy(
        policy_path, expected_policy_id, expected_policy_sha,
        RUNNER_POLICY_PRODUCT, "allowedRunners",
    )
    validate_runner_policy(policy)
    at = package_tool.verification_time(verification_time)
    issued = package_tool.parse_time(attestation["issuedAt"], "runner issuedAt")
    expires = package_tool.parse_time(attestation["expiresAt"], "runner expiresAt")
    if (issued > at + timedelta(minutes=5) or at >= expires
            or (expires - issued).total_seconds() > policy["maxAttestationLifetimeSeconds"]):
        raise ValueError("runner attestation is expired, future-dated or too long")
    revoked = validate_revocations(policy)
    matches = [item for item in policy["allowedRunners"]
               if item["runnerId"] == attestation["runnerId"]
               and item["keyId"] == attestation["keyId"]]
    if len(matches) != 1 or attestation["keyId"] in revoked:
        raise ValueError("runner identity is not trusted or its key is revoked")
    runner = matches[0]
    if (attestation["repository"] not in runner["repositories"]
            or attestation["workflow"] not in runner["workflows"]
            or issued < package_tool.parse_time(runner["notBefore"], "notBefore")
            or at >= package_tool.parse_time(runner["notAfter"], "notAfter")):
        raise ValueError("runner repository, workflow or validity scope is not trusted")
    public_key = package_tool.policy_public_key(policy_file, runner["publicKey"])
    public_sha = package_tool.sha256_file(public_key)
    if public_sha != runner["publicKeySha256"]:
        raise ValueError("runner public key SHA-256 is not trusted")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        key = load_pem_public_key(public_key.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("runner public key is not Ed25519")
        key.verify(signature_bytes(attestation["signature"]), canonical_payload(attestation))
    except Exception as error:
        raise ValueError("runner attestation signature verification failed") from error
    return attestation, {
        "attestationSha256": attestation_sha,
        "policyId": policy["policyId"],
        "policySha256": policy_sha,
        "runnerId": attestation["runnerId"],
        "repository": attestation["repository"],
        "sourceRevision": attestation["sourceRevision"],
        "workflow": attestation["workflow"],
        "jobId": attestation["jobId"],
        "runId": attestation["runId"],
        "keyId": attestation["keyId"],
        "publicKeySha256": public_sha,
        "issuedAt": attestation["issuedAt"],
        "expiresAt": attestation["expiresAt"],
    }


def verify_runner_attestation(attestation_path: str | Path, report_path: str | Path,
                              evidence_path: str | Path, junit_path: str | Path | None,
                              policy_path: str | Path, expected_policy_id: str,
                              expected_policy_sha: str, verification_time: str | None) \
        -> dict[str, Any]:
    report, report_sha, evidence, evidence_sha = execution_inputs(
        Path(report_path), Path(evidence_path), Path(junit_path) if junit_path else None,
    )
    attestation, verification = verify_runner_signature(
        attestation_path, policy_path, expected_policy_id,
        expected_policy_sha, verification_time,
    )
    expected = {
        "impactReportSha256": report_sha,
        "impactInputSetSha256": report["inputSetSha256"],
        "candidateLockSha256": report["candidateLockSha256"],
        "executionEvidenceSha256": evidence_sha,
        "junitSha256": evidence["junitSha256"],
        "ctestExecutableSha256": evidence["ctestExecutableSha256"],
        "ctestCatalogSha256": evidence["ctestCatalogSha256"],
        "ctestCommandSha256": evidence["ctestCommandSha256"],
    }
    if any(attestation.get(key) != value for key, value in expected.items()):
        raise ValueError("runner attestation is stale or binds different execution evidence")
    return verification


def runner_verify_command(args: argparse.Namespace) -> int:
    try:
        evidence = verify_runner_attestation(
            args.attestation, args.report, args.evidence, args.junit,
            args.trust_policy, args.expected_trust_policy_id,
            args.expected_trust_policy_sha256, args.verification_time,
        )
        report = {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRunnerAttestationVerification",
            "operation": "team-contract-runner-verify",
            "passed": True,
            **evidence,
        }
        if args.verification_report:
            package_tool.write_json(Path(args.verification_report).resolve(), report)
        print(f"PDR_TEAM_CONTRACT_RUNNER_VERIFY_PASS runner={evidence['runnerId']} "
              f"run={evidence['runId']}")
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_RUNNER_VERIFY_ERROR: {error}", file=sys.stderr)
        return 2


def validate_gate_authorization_policy(document: dict[str, Any]) -> None:
    if (set(document) != {
            "schemaVersion", "product", "policyId", "maxAuthorizationLifetimeSeconds",
            "allowedAuthorizers", "revokedKeys",
        } or type(document.get("maxAuthorizationLifetimeSeconds")) is not int
            or not 60 <= document["maxAuthorizationLifetimeSeconds"] <= MAX_LIFETIME):
        raise ValueError("Gate authorization policy is malformed")
    fields = {
        "authorizerId", "keyId", "algorithm", "publicKey", "publicKeySha256",
        "registryIds", "channels", "notBefore", "notAfter",
    }
    keys: set[str] = set()
    authorizers: set[str] = set()
    for item in document["allowedAuthorizers"]:
        if (not isinstance(item, dict) or set(item) != fields
                or not package_tool.IDENTIFIER.fullmatch(str(item.get("authorizerId", "")))
                or not package_tool.IDENTIFIER.fullmatch(str(item.get("keyId", "")))
                or item.get("algorithm") != "Ed25519"
                or not re.fullmatch(r"keys/[A-Za-z0-9._-]+\.pem",
                                    str(item.get("publicKey", "")))
                or not package_tool.SHA256.fullmatch(str(item.get("publicKeySha256", "")))
                or not isinstance(item.get("registryIds"), list) or not item["registryIds"]
                or len(item["registryIds"]) != len(set(item["registryIds"]))
                or any(not package_tool.IDENTIFIER.fullmatch(str(value))
                       for value in item["registryIds"])
                or not isinstance(item.get("channels"), list) or not item["channels"]
                or len(item["channels"]) != len(set(item["channels"]))
                or any(not package_tool.IDENTIFIER.fullmatch(str(value))
                       for value in item["channels"])
                or item["keyId"] in keys or item["authorizerId"] in authorizers):
            raise ValueError("Gate authorization policy entry is malformed")
        if package_tool.parse_time(item["notBefore"], "notBefore") >= \
                package_tool.parse_time(item["notAfter"], "notAfter"):
            raise ValueError("Gate authorization policy validity window is reversed")
        keys.add(item["keyId"])
        authorizers.add(item["authorizerId"])
    validate_revocations(document)


def validate_gate_document(document: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "operation", "passed", "impactReportSha256",
        "impactInputSetSha256", "candidateLockSha256", "executionEvidenceSha256",
        "junitSha256", "runnerAttestation", "approvalPolicy", "requiredOwners",
        "approvedOwners", "approvals",
    }
    runner = document.get("runnerAttestation")
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != gate_tool.GATE_PRODUCT
            or document.get("operation") != "team-contract-impact-gate"
            or document.get("passed") is not True
            or any(not package_tool.SHA256.fullmatch(str(document.get(field, "")))
                   for field in ("impactReportSha256", "impactInputSetSha256",
                                 "candidateLockSha256", "executionEvidenceSha256"))
            or (document.get("junitSha256") is not None
                and not package_tool.SHA256.fullmatch(str(document["junitSha256"])))
            or not isinstance(runner, dict)
            or not package_tool.SHA256.fullmatch(str(runner.get("attestationSha256", "")))
            or not isinstance(document.get("requiredOwners"), list)
            or document.get("approvedOwners") != document["requiredOwners"]
            or len(document["requiredOwners"]) != len(set(document["requiredOwners"]))
            or not isinstance(document.get("approvals"), list)):
        raise ValueError("team contract impact Gate is malformed")


def validate_gate_authorization(document: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "operation", "decision", "authorizationId",
        "registryId", "channels", "gateReportSha256", "candidateLockSha256",
        "impactReportSha256", "executionEvidenceSha256", "runnerAttestationSha256",
        "issuedAt", "expiresAt", "authorizerId", "keyId", "signature",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != GATE_AUTH_PRODUCT
            or document.get("operation") != "team-contract-gate-authorize"
            or document.get("decision") != "approve"
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(field, "")))
                   for field in ("authorizationId", "registryId", "authorizerId", "keyId"))
            or not isinstance(document.get("channels"), list) or not document["channels"]
            or len(document["channels"]) != len(set(document["channels"]))
            or any(not package_tool.IDENTIFIER.fullmatch(str(value))
                   for value in document["channels"])
            or any(not package_tool.SHA256.fullmatch(str(document.get(field, "")))
                   for field in ("gateReportSha256", "candidateLockSha256",
                                 "impactReportSha256", "executionEvidenceSha256",
                                 "runnerAttestationSha256"))):
        raise ValueError("Gate authorization is malformed")
    issued = package_tool.parse_time(document["issuedAt"], "authorization issuedAt")
    expires = package_tool.parse_time(document["expiresAt"], "authorization expiresAt")
    if issued >= expires:
        raise ValueError("Gate authorization validity window is reversed")
    signature_bytes(document.get("signature"))


def gate_authorize_command(args: argparse.Namespace) -> int:
    try:
        if (any(not package_tool.IDENTIFIER.fullmatch(str(value)) for value in
                (args.authorization_id, args.registry_id, args.authorizer_id, args.key_id))
                or not args.channel or len(args.channel) != len(set(args.channel))
                or any(not package_tool.IDENTIFIER.fullmatch(str(value))
                       for value in args.channel)):
            raise ValueError("Gate authorization identity or scope is invalid")
        if not 60 <= args.lifetime_seconds <= MAX_LIFETIME:
            raise ValueError("Gate authorization lifetime is outside the supported range")
        gate_path = package_tool.resolved_path(args.gate_report, "team contract impact Gate")
        gate, gate_sha = impact_tool.load_json(gate_path, "team contract impact Gate")
        validate_gate_document(gate)
        with tempfile.TemporaryDirectory(prefix="pdr-gate-replay-") as directory:
            replay_path = Path(directory) / "gate.json"
            replay_args = argparse.Namespace(
                report=args.report, evidence=args.evidence, junit=args.junit,
                ctest=args.ctest, test_dir=args.test_dir, config=args.config,
                approval_policy=args.approval_policy,
                expected_approval_policy_id=args.expected_approval_policy_id,
                expected_approval_policy_sha256=args.expected_approval_policy_sha256,
                approval=args.approval, runner_attestation=args.runner_attestation,
                runner_trust_policy=args.runner_trust_policy,
                expected_runner_trust_policy_id=args.expected_runner_trust_policy_id,
                expected_runner_trust_policy_sha256=args.expected_runner_trust_policy_sha256,
                verification_time=args.verification_time, gate_report=str(replay_path),
            )
            if gate_tool.gate_command(replay_args) != 0:
                raise ValueError("Gate replay validation failed")
            replay, _ = impact_tool.load_json(replay_path, "replayed impact Gate")
            if replay != gate:
                raise ValueError("Gate report differs from independently replayed validation")
        issued = package_tool.verification_time(args.issued_at)
        authorization = {
            "schemaVersion": 1,
            "product": GATE_AUTH_PRODUCT,
            "operation": "team-contract-gate-authorize",
            "decision": "approve",
            "authorizationId": args.authorization_id,
            "registryId": args.registry_id,
            "channels": sorted(args.channel),
            "gateReportSha256": gate_sha,
            "candidateLockSha256": gate["candidateLockSha256"],
            "impactReportSha256": gate["impactReportSha256"],
            "executionEvidenceSha256": gate["executionEvidenceSha256"],
            "runnerAttestationSha256": gate["runnerAttestation"]["attestationSha256"],
            "issuedAt": issued.isoformat(),
            "expiresAt": (issued + timedelta(seconds=args.lifetime_seconds)).isoformat(),
            "authorizerId": args.authorizer_id,
            "keyId": args.key_id,
        }
        authorization["signature"] = base64.b64encode(
            private_key(args).sign(canonical_payload(authorization))
        ).decode("ascii")
        validate_gate_authorization(authorization)
        gate_tool.exclusive_json(Path(args.output), authorization)
        print(f"PDR_TEAM_CONTRACT_GATE_AUTHORIZE_PASS id={args.authorization_id} "
              f"registry={args.registry_id}")
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_GATE_AUTHORIZE_ERROR: {error}", file=sys.stderr)
        return 2


def verify_gate_authorization(gate_path: str | Path, authorization_path: str | Path,
                              policy_path: str | Path, expected_policy_id: str,
                              expected_policy_sha: str, expected_registry_id: str,
                              expected_channel: str, verification_time: str | None) \
        -> dict[str, Any]:
    gate_file = package_tool.resolved_path(gate_path, "team contract impact Gate")
    gate, gate_sha = impact_tool.load_json(gate_file, "team contract impact Gate")
    validate_gate_document(gate)
    auth_file = package_tool.resolved_path(authorization_path, "Gate authorization")
    authorization, auth_sha = impact_tool.load_json(auth_file, "Gate authorization")
    validate_gate_authorization(authorization)
    expected = {
        "gateReportSha256": gate_sha,
        "candidateLockSha256": gate["candidateLockSha256"],
        "impactReportSha256": gate["impactReportSha256"],
        "executionEvidenceSha256": gate["executionEvidenceSha256"],
        "runnerAttestationSha256": gate["runnerAttestation"]["attestationSha256"],
    }
    if any(authorization.get(key) != value for key, value in expected.items()):
        raise ValueError("Gate authorization is stale or binds a different Gate")
    if (authorization["registryId"] != expected_registry_id
            or expected_channel not in authorization["channels"]):
        raise ValueError("Gate authorization does not permit this Registry channel")
    policy, policy_file, policy_sha = load_policy(
        policy_path, expected_policy_id, expected_policy_sha,
        GATE_AUTH_POLICY_PRODUCT, "allowedAuthorizers",
    )
    validate_gate_authorization_policy(policy)
    at = package_tool.verification_time(verification_time)
    issued = package_tool.parse_time(authorization["issuedAt"], "authorization issuedAt")
    expires = package_tool.parse_time(authorization["expiresAt"], "authorization expiresAt")
    if (issued > at + timedelta(minutes=5) or at >= expires
            or (expires - issued).total_seconds() > policy["maxAuthorizationLifetimeSeconds"]):
        raise ValueError("Gate authorization is expired, future-dated or too long")
    revoked = validate_revocations(policy)
    matches = [item for item in policy["allowedAuthorizers"]
               if item["authorizerId"] == authorization["authorizerId"]
               and item["keyId"] == authorization["keyId"]]
    if len(matches) != 1 or authorization["keyId"] in revoked:
        raise ValueError("Gate authorizer is not trusted or its key is revoked")
    authorizer = matches[0]
    if (expected_registry_id not in authorizer["registryIds"]
            or expected_channel not in authorizer["channels"]
            or issued < package_tool.parse_time(authorizer["notBefore"], "notBefore")
            or at >= package_tool.parse_time(authorizer["notAfter"], "notAfter")):
        raise ValueError("Gate authorizer Registry, channel or validity scope is not trusted")
    public_key = package_tool.policy_public_key(policy_file, authorizer["publicKey"])
    public_sha = package_tool.sha256_file(public_key)
    if public_sha != authorizer["publicKeySha256"]:
        raise ValueError("Gate authorizer public key SHA-256 is not trusted")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        key = load_pem_public_key(public_key.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Gate authorizer public key is not Ed25519")
        key.verify(signature_bytes(authorization["signature"]),
                   canonical_payload(authorization))
    except Exception as error:
        raise ValueError("Gate authorization signature verification failed") from error
    return {
        "authorizationId": authorization["authorizationId"],
        "authorizationSha256": auth_sha,
        "gateReportSha256": gate_sha,
        "candidateLockSha256": authorization["candidateLockSha256"],
        "registryId": authorization["registryId"],
        "channels": authorization["channels"],
        "policyId": policy["policyId"],
        "policySha256": policy_sha,
        "authorizerId": authorization["authorizerId"],
        "keyId": authorization["keyId"],
        "publicKeySha256": public_sha,
        "issuedAt": authorization["issuedAt"],
        "expiresAt": authorization["expiresAt"],
    }


def gate_authorization_verify_command(args: argparse.Namespace) -> int:
    try:
        evidence = verify_gate_authorization(
            args.gate_report, args.authorization, args.authorization_policy,
            args.expected_authorization_policy_id,
            args.expected_authorization_policy_sha256, args.expected_registry_id,
            args.expected_channel, args.verification_time,
        )
        report = {
            "schemaVersion": 1,
            "product": GATE_AUTH_VERIFICATION_PRODUCT,
            "operation": "team-contract-gate-authorization-verify",
            "passed": True,
            **evidence,
        }
        if args.verification_report:
            package_tool.write_json(Path(args.verification_report).resolve(), report)
        print(f"PDR_TEAM_CONTRACT_GATE_AUTHORIZATION_VERIFY_PASS "
              f"id={evidence['authorizationId']}")
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_GATE_AUTHORIZATION_VERIFY_ERROR: {error}", file=sys.stderr)
        return 2


def validate_anchor(document: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "operation", "anchorId", "anchorServiceId",
        "registryId", "registryRevision", "registryStateSha256",
        "previousAnchorSha256", "issuedAt", "keyId", "signature",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != ANCHOR_PRODUCT
            or document.get("operation") != "team-contract-registry-anchor"
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(field, "")))
                   for field in ("anchorId", "anchorServiceId", "registryId", "keyId"))
            or type(document.get("registryRevision")) is not int
            or document["registryRevision"] < 0
            or not package_tool.SHA256.fullmatch(str(document.get("registryStateSha256", "")))
            or (document.get("previousAnchorSha256") is not None
                and not package_tool.SHA256.fullmatch(str(document["previousAnchorSha256"])))):
        raise ValueError("Registry external anchor is malformed")
    package_tool.parse_time(document["issuedAt"], "anchor issuedAt")
    signature_bytes(document["signature"])


def outside_registry(output: Path, root: Path) -> None:
    resolved = output.absolute()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return
    raise ValueError("Registry anchor must be stored outside the Registry root")


def registry_anchor_command(args: argparse.Namespace) -> int:
    try:
        root = registry_tool.registry_root(args.registry)
        pointer, state = registry_tool.verified_current(root, args)
        output = Path(args.output).absolute()
        outside_registry(output, root)
        if any(not package_tool.IDENTIFIER.fullmatch(value)
               for value in (args.anchor_id, args.anchor_service_id, args.key_id)):
            raise ValueError("Registry anchor identity is invalid")
        previous_sha = None
        if args.previous_anchor:
            previous_path = package_tool.resolved_path(args.previous_anchor, "previous Registry anchor")
            outside_registry(previous_path, root)
            previous, _ = impact_tool.load_json(previous_path, "previous Registry anchor")
            validate_anchor(previous)
            if (previous["registryId"] != state["registryId"]
                    or previous["registryRevision"] >= state["revision"]):
                raise ValueError("previous Registry anchor is not an earlier state of this Registry")
            previous_sha = package_tool.sha256_file(previous_path)
        anchor = {
            "schemaVersion": 1,
            "product": ANCHOR_PRODUCT,
            "operation": "team-contract-registry-anchor",
            "anchorId": args.anchor_id,
            "anchorServiceId": args.anchor_service_id,
            "registryId": state["registryId"],
            "registryRevision": state["revision"],
            "registryStateSha256": pointer["stateSha256"],
            "previousAnchorSha256": previous_sha,
            "issuedAt": package_tool.verification_time(args.issued_at).isoformat(),
            "keyId": args.key_id,
        }
        anchor["signature"] = base64.b64encode(
            private_key(args).sign(canonical_payload(anchor))
        ).decode("ascii")
        validate_anchor(anchor)
        gate_tool.exclusive_json(output, anchor)
        print(f"PDR_TEAM_CONTRACT_REGISTRY_ANCHOR_PASS id={args.anchor_id} "
              f"revision={state['revision']}")
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_ANCHOR_ERROR: {error}", file=sys.stderr)
        return 2


def validate_anchor_policy(document: dict[str, Any]) -> None:
    if set(document) != {"schemaVersion", "product", "policyId", "allowedAnchors", "revokedKeys"}:
        raise ValueError("Registry anchor policy is malformed")
    fields = {
        "anchorServiceId", "keyId", "algorithm", "publicKey", "publicKeySha256",
        "registryIds", "notBefore", "notAfter",
    }
    keys: set[str] = set()
    for item in document["allowedAnchors"]:
        if (not isinstance(item, dict) or set(item) != fields
                or not package_tool.IDENTIFIER.fullmatch(str(item.get("anchorServiceId", "")))
                or not package_tool.IDENTIFIER.fullmatch(str(item.get("keyId", "")))
                or item.get("algorithm") != "Ed25519"
                or not re.fullmatch(r"keys/[A-Za-z0-9._-]+\.pem",
                                    str(item.get("publicKey", "")))
                or not package_tool.SHA256.fullmatch(str(item.get("publicKeySha256", "")))
                or not isinstance(item.get("registryIds"), list) or not item["registryIds"]
                or len(item["registryIds"]) != len(set(item["registryIds"]))
                or any(not package_tool.IDENTIFIER.fullmatch(str(value))
                       for value in item["registryIds"])
                or item["keyId"] in keys):
            raise ValueError("Registry anchor policy entry is malformed")
        if package_tool.parse_time(item["notBefore"], "notBefore") >= \
                package_tool.parse_time(item["notAfter"], "notAfter"):
            raise ValueError("Registry anchor policy validity window is reversed")
        keys.add(item["keyId"])
    validate_revocations(document)


def anchored_state_sha(root: Path, pointer: dict[str, Any], state: dict[str, Any],
                       revision: int) -> str:
    if pointer["revision"] < revision:
        raise ValueError("current Registry is older than the external anchor")
    digest = pointer["stateSha256"]
    current = state
    while current["revision"] > revision:
        digest = current["previousStateSha256"]
        current = impact_tool.load_json(
            registry_tool.state_path(root, current["revision"] - 1, digest),
            "anchored Registry state",
        )[0]
        registry_tool.validate_state(current)
    return digest


def registry_anchor_verify_command(args: argparse.Namespace) -> int:
    try:
        root = registry_tool.registry_root(args.registry)
        pointer, state = registry_tool.verified_current(root, args)
        anchor_path = package_tool.resolved_path(args.anchor, "Registry external anchor")
        outside_registry(anchor_path, root)
        anchor, anchor_sha = impact_tool.load_json(anchor_path, "Registry external anchor")
        validate_anchor(anchor)
        policy, policy_path, policy_sha = load_policy(
            args.anchor_policy, args.expected_anchor_policy_id,
            args.expected_anchor_policy_sha256, ANCHOR_POLICY_PRODUCT, "allowedAnchors",
        )
        validate_anchor_policy(policy)
        at = package_tool.verification_time(args.verification_time)
        issued = package_tool.parse_time(anchor["issuedAt"], "anchor issuedAt")
        revoked = validate_revocations(policy)
        matches = [item for item in policy["allowedAnchors"]
                   if item["anchorServiceId"] == anchor["anchorServiceId"]
                   and item["keyId"] == anchor["keyId"]]
        if len(matches) != 1 or anchor["keyId"] in revoked:
            raise ValueError("Registry anchor service is not trusted or its key is revoked")
        signer = matches[0]
        if (anchor["registryId"] != state["registryId"]
                or anchor["registryId"] not in signer["registryIds"]
                or issued > at + timedelta(minutes=5)
                or issued < package_tool.parse_time(signer["notBefore"], "notBefore")
                or at >= package_tool.parse_time(signer["notAfter"], "notAfter")):
            raise ValueError("Registry anchor identity, time or Registry scope is not trusted")
        public_key = package_tool.policy_public_key(policy_path, signer["publicKey"])
        public_sha = package_tool.sha256_file(public_key)
        if public_sha != signer["publicKeySha256"]:
            raise ValueError("Registry anchor public key SHA-256 is not trusted")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
            key = load_pem_public_key(public_key.read_bytes())
            if not isinstance(key, Ed25519PublicKey):
                raise ValueError("Registry anchor public key is not Ed25519")
            key.verify(signature_bytes(anchor["signature"]), canonical_payload(anchor))
        except Exception as error:
            raise ValueError("Registry anchor signature verification failed") from error
        if anchored_state_sha(
                root, pointer, state, anchor["registryRevision"]
        ) != anchor["registryStateSha256"]:
            raise ValueError("current Registry chain does not contain the externally anchored state")
        report = {
            "schemaVersion": 1,
            "product": ANCHOR_VERIFICATION_PRODUCT,
            "operation": "team-contract-registry-anchor-verify",
            "passed": True,
            "anchorId": anchor["anchorId"],
            "anchorSha256": anchor_sha,
            "anchorServiceId": anchor["anchorServiceId"],
            "registryId": state["registryId"],
            "anchoredRevision": anchor["registryRevision"],
            "currentRevision": state["revision"],
            "currentStateSha256": pointer["stateSha256"],
            "policyId": policy["policyId"],
            "policySha256": policy_sha,
            "keyId": anchor["keyId"],
            "publicKeySha256": public_sha,
            "verifiedAt": at.isoformat(),
        }
        if args.verification_report:
            package_tool.write_json(Path(args.verification_report).resolve(), report)
        print(f"PDR_TEAM_CONTRACT_REGISTRY_ANCHOR_VERIFY_PASS "
              f"anchored={anchor['registryRevision']} current={state['revision']}")
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_ANCHOR_VERIFY_ERROR: {error}", file=sys.stderr)
        return 2


def add_private_key_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--key-id", required=True)
    command.add_argument("--private-key-environment", required=True)
    command.add_argument("--private-key-passphrase-environment")


def add_registry_trust_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--trust-policy", required=True)
    command.add_argument("--expected-trust-policy-id", required=True)
    command.add_argument("--expected-trust-policy-sha256", required=True)
    command.add_argument("--verification-time")
    command.add_argument("--maximum-files", type=int, default=package_tool.MAX_FILES_DEFAULT)
    command.add_argument("--maximum-expanded-bytes", type=int,
                         default=package_tool.MAX_EXPANDED_BYTES_DEFAULT)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    attest = commands.add_parser("runner-attest", help="sign exact impact execution evidence")
    attest.add_argument("--report", required=True)
    attest.add_argument("--evidence", required=True)
    attest.add_argument("--junit")
    attest.add_argument("--runner-id", required=True)
    attest.add_argument("--repository", required=True)
    attest.add_argument("--source-revision", required=True)
    attest.add_argument("--workflow", required=True)
    attest.add_argument("--job-id", required=True)
    attest.add_argument("--run-id", required=True)
    attest.add_argument("--issued-at")
    attest.add_argument("--lifetime-seconds", type=int, default=3600)
    attest.add_argument("--output", required=True)
    add_private_key_arguments(attest)
    attest.set_defaults(handler=runner_attest_command)
    verify = commands.add_parser("runner-verify", help="verify runner scope and signed evidence")
    verify.add_argument("--attestation", required=True)
    verify.add_argument("--report", required=True)
    verify.add_argument("--evidence", required=True)
    verify.add_argument("--junit")
    verify.add_argument("--trust-policy", required=True)
    verify.add_argument("--expected-trust-policy-id", required=True)
    verify.add_argument("--expected-trust-policy-sha256", required=True)
    verify.add_argument("--verification-time")
    verify.add_argument("--verification-report")
    verify.set_defaults(handler=runner_verify_command)
    authorize = commands.add_parser(
        "gate-authorize", help="replay and sign a complete team contract impact Gate"
    )
    authorize.add_argument("--gate-report", required=True)
    authorize.add_argument("--report", required=True)
    authorize.add_argument("--evidence", required=True)
    authorize.add_argument("--junit", required=True)
    authorize.add_argument("--ctest")
    authorize.add_argument("--test-dir")
    authorize.add_argument("--config", default="Release")
    authorize.add_argument("--approval-policy")
    authorize.add_argument("--expected-approval-policy-id")
    authorize.add_argument("--expected-approval-policy-sha256")
    authorize.add_argument("--approval", action="append", default=[])
    authorize.add_argument("--runner-attestation")
    authorize.add_argument("--runner-trust-policy")
    authorize.add_argument("--expected-runner-trust-policy-id")
    authorize.add_argument("--expected-runner-trust-policy-sha256")
    authorize.add_argument("--verification-time")
    authorize.add_argument("--registry-id", required=True)
    authorize.add_argument("--channel", action="append", required=True)
    authorize.add_argument("--authorization-id", required=True)
    authorize.add_argument("--authorizer-id", required=True)
    authorize.add_argument("--issued-at")
    authorize.add_argument("--lifetime-seconds", type=int, default=3600)
    authorize.add_argument("--output", required=True)
    add_private_key_arguments(authorize)
    authorize.set_defaults(handler=gate_authorize_command)
    auth_verify = commands.add_parser(
        "gate-authorization-verify", help="verify a Registry-scoped Gate authorization"
    )
    auth_verify.add_argument("--gate-report", required=True)
    auth_verify.add_argument("--authorization", required=True)
    auth_verify.add_argument("--authorization-policy", required=True)
    auth_verify.add_argument("--expected-authorization-policy-id", required=True)
    auth_verify.add_argument("--expected-authorization-policy-sha256", required=True)
    auth_verify.add_argument("--expected-registry-id", required=True)
    auth_verify.add_argument("--expected-channel", required=True)
    auth_verify.add_argument("--verification-time")
    auth_verify.add_argument("--verification-report")
    auth_verify.set_defaults(handler=gate_authorization_verify_command)
    anchor = commands.add_parser("registry-anchor", help="sign current Registry state externally")
    anchor.add_argument("--registry", required=True)
    anchor.add_argument("--anchor-id", required=True)
    anchor.add_argument("--anchor-service-id", required=True)
    anchor.add_argument("--previous-anchor")
    anchor.add_argument("--issued-at")
    anchor.add_argument("--output", required=True)
    add_private_key_arguments(anchor)
    add_registry_trust_arguments(anchor)
    anchor.set_defaults(handler=registry_anchor_command)
    anchor_verify = commands.add_parser(
        "registry-anchor-verify", help="detect Registry rollback against an external anchor"
    )
    anchor_verify.add_argument("--registry", required=True)
    anchor_verify.add_argument("--anchor", required=True)
    anchor_verify.add_argument("--anchor-policy", required=True)
    anchor_verify.add_argument("--expected-anchor-policy-id", required=True)
    anchor_verify.add_argument("--expected-anchor-policy-sha256", required=True)
    anchor_verify.add_argument("--verification-report")
    add_registry_trust_arguments(anchor_verify)
    anchor_verify.set_defaults(handler=registry_anchor_verify_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
