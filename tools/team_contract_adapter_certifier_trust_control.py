#!/usr/bin/env python3
"""Govern staged Adapter certifier trust-policy activation."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import team_contract_adapter_conformance_trust as trust_tool
import team_contract_governance_approval as approval_tool
import team_contract_package as package_tool
import team_contract_registry as registry_tool
import process_file_lease as process_lease


PRODUCT = "PocoDDSRuntimeTeamContractAdapterCertifierTrustControl"
GOVERNANCE_PRODUCT = PRODUCT + "GovernancePolicy"
PROPOSAL_PRODUCT = PRODUCT + "Proposal"
APPROVAL_PRODUCT = PRODUCT + "Approval"
MAX_APPROVERS = 64
MAX_LIFETIME = 86400


def _time(value: str | None) -> Any:
    return package_tool.verification_time(value)


def _load_json(path_value: str | Path, label: str) -> tuple[dict[str, Any], Path, bytes, str]:
    path = package_tool.resolved_path(path_value, label)
    content = path.read_bytes()
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} is malformed")
    return document, path, content, package_tool.sha256_bytes(content)


def _pinned(path_value: str | Path, expected_sha256: str, label: str) \
        -> tuple[dict[str, Any], Path, bytes, str]:
    if package_tool.SHA256.fullmatch(str(expected_sha256).lower()) is None:
        raise ValueError(f"{label} expected SHA is malformed")
    result = _load_json(path_value, label)
    if result[3] != str(expected_sha256).lower():
        raise ValueError(f"{label} SHA changed")
    return result


def validate_governance(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "policyId",
        "standardMinimumApprovals", "emergencyMinimumApprovals",
        "maxStandardLifetimeSeconds", "maxEmergencyLifetimeSeconds",
        "allowedApprovers", "activatorIds", "revokedKeys",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != GOVERNANCE_PRODUCT
            or package_tool.IDENTIFIER.fullmatch(str(document.get("policyId", ""))) is None):
        raise ValueError("Adapter certifier governance policy is malformed")
    standard = document.get("standardMinimumApprovals")
    emergency = document.get("emergencyMinimumApprovals")
    standard_lifetime = document.get("maxStandardLifetimeSeconds")
    emergency_lifetime = document.get("maxEmergencyLifetimeSeconds")
    if (type(standard) is not int or not 2 <= standard <= MAX_APPROVERS
            or type(emergency) is not int or not 1 <= emergency <= MAX_APPROVERS
            or type(standard_lifetime) is not int
            or not 300 <= standard_lifetime <= MAX_LIFETIME
            or type(emergency_lifetime) is not int
            or not 60 <= emergency_lifetime <= 3600
            or emergency_lifetime > standard_lifetime):
        raise ValueError("Adapter certifier governance thresholds are malformed")
    approvers = document.get("allowedApprovers")
    activators = document.get("activatorIds")
    revoked = document.get("revokedKeys")
    if (not isinstance(approvers, list) or not approvers
            or len(approvers) > MAX_APPROVERS
            or not isinstance(activators, list) or not activators
            or activators != sorted(set(activators))
            or any(package_tool.IDENTIFIER.fullmatch(str(item)) is None for item in activators)
            or not isinstance(revoked, list) or len(revoked) > MAX_APPROVERS):
        raise ValueError("Adapter certifier governance identities are malformed")
    people: set[str] = set()
    keys: set[str] = set()
    for item in approvers:
        if (not isinstance(item, dict) or set(item) != {
                "approverId", "keyId", "algorithm", "publicKeySha256", "roles"
                } or any(package_tool.IDENTIFIER.fullmatch(str(item.get(name, ""))) is None
                         for name in ("approverId", "keyId"))
                or item.get("algorithm") != "Ed25519"
                or package_tool.SHA256.fullmatch(str(item.get("publicKeySha256", ""))) is None
                or item.get("roles") != sorted(set(item.get("roles", [])))
                or not item.get("roles")
                or any(role not in {"standard", "emergency-revocation"}
                       for role in item["roles"])
                or item["approverId"] in people or item["keyId"] in keys):
            raise ValueError("Adapter certifier governance approver is malformed")
        people.add(item["approverId"])
        keys.add(item["keyId"])
    eligible_standard = {item["approverId"] for item in approvers
                         if "standard" in item["roles"]}
    eligible_emergency = {item["approverId"] for item in approvers
                          if "emergency-revocation" in item["roles"]}
    if standard > len(eligible_standard) or emergency > len(eligible_emergency):
        raise ValueError("Adapter certifier governance quorum is impossible")
    revoked_ids: set[str] = set()
    for item in revoked:
        if (not isinstance(item, dict) or set(item) != {"keyId", "revokedAt", "reason"}
                or package_tool.IDENTIFIER.fullmatch(str(item.get("keyId", ""))) is None
                or not isinstance(item.get("reason"), str) or not item["reason"].strip()
                or len(item["reason"]) > 512 or item["keyId"] in revoked_ids):
            raise ValueError("Adapter certifier governance revocation is malformed")
        package_tool.parse_time(item["revokedAt"], "governance revokedAt")
        revoked_ids.add(item["keyId"])


def validate_proposal(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "operation", "proposalId", "mode",
        "trustPolicyId", "currentGeneration", "currentPolicySha256",
        "candidateGeneration", "candidatePolicySha256", "governancePolicyId",
        "governancePolicySha256", "proposerId", "ticket", "reason",
        "issuedAt", "expiresAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != PROPOSAL_PRODUCT
            or document.get("operation") != "adapter-certifier-trust-propose"
            or document.get("mode") not in {"standard", "emergency-revocation"}
            or any(package_tool.IDENTIFIER.fullmatch(str(document.get(name, ""))) is None
                   for name in ("proposalId", "trustPolicyId", "governancePolicyId",
                                "proposerId", "ticket"))
            or any(package_tool.SHA256.fullmatch(str(document.get(name, ""))) is None
                   for name in ("currentPolicySha256", "candidatePolicySha256",
                                "governancePolicySha256"))
            or type(document.get("currentGeneration")) is not int
            or type(document.get("candidateGeneration")) is not int
            or document["candidateGeneration"] != document["currentGeneration"] + 1
            or not isinstance(document.get("reason"), str)
            or not document["reason"].strip() or len(document["reason"]) > 512):
        raise ValueError("Adapter certifier trust proposal is malformed")
    issued = package_tool.parse_time(document["issuedAt"], "proposal issuedAt")
    expires = package_tool.parse_time(document["expiresAt"], "proposal expiresAt")
    if issued >= expires:
        raise ValueError("Adapter certifier trust proposal lifetime is invalid")


def validate_approval(document: Any) -> None:
    base_fields = {
            "schemaVersion", "product", "algorithm", "approverId", "keyId",
            "proposalSha256", "signature"
    }
    version = document.get("schemaVersion") if isinstance(document, dict) else None
    fields = base_fields | (
        approval_tool.SIGNER_DESCRIPTOR_FIELDS if version == 2 else
        approval_tool.SIGNER_DESCRIPTOR_FIELDS
        | approval_tool.SIGNER_ADMISSION_FIELDS
        if version == 3 else set()
    )
    if (not isinstance(document, dict) or set(document) != fields
            or version not in {1, 2, 3}
            or document.get("product") != APPROVAL_PRODUCT
            or document.get("algorithm") != "Ed25519"
            or any(package_tool.IDENTIFIER.fullmatch(str(document.get(name, ""))) is None
                   for name in ("approverId", "keyId"))
            or package_tool.SHA256.fullmatch(str(document.get("proposalSha256", ""))) is None):
        raise ValueError("Adapter certifier trust approval is malformed")
    try:
        signature = base64.b64decode(document["signature"], validate=True)
    except (TypeError, ValueError) as error:
        raise ValueError("Adapter certifier trust approval signature is malformed") from error
    if len(signature) != 64:
        raise ValueError("Adapter certifier trust approval signature is malformed")
    if version in {2, 3}:
        approval_tool.validate_signer_descriptor(
            document, admitted=version == 3
        )


def validate_activation_report(document: Any) -> None:
    base_fields = {
        "schemaVersion", "product", "passed", "proposalId", "mode",
        "trustPolicyId", "previousGeneration", "previousPolicySha256",
        "generation", "policySha256", "governancePolicyId",
        "governancePolicySha256", "proposerId", "activatorId",
        "approvals", "emergencyRevokedKeyIds", "activatedAt",
    }
    version = document.get("schemaVersion") if isinstance(document, dict) else None
    fields = base_fields | (
        {"signerReadmissionEvidenceSha256"} if version == 2 else set()
    )
    if (not isinstance(document, dict) or set(document) != fields
            or version not in {1, 2}
            or document.get("product") != PRODUCT + "ActivationReport"
            or document.get("passed") is not True
            or document.get("mode") not in {"standard", "emergency-revocation"}
            or any(package_tool.IDENTIFIER.fullmatch(str(document.get(name, ""))) is None
                   for name in ("proposalId", "trustPolicyId", "governancePolicyId",
                                "proposerId", "activatorId"))
            or any(package_tool.SHA256.fullmatch(str(document.get(name, ""))) is None
                   for name in ("previousPolicySha256", "policySha256",
                                "governancePolicySha256"))
            or type(document.get("previousGeneration")) is not int
            or type(document.get("generation")) is not int
            or document["generation"] != document["previousGeneration"] + 1
            or not isinstance(document.get("approvals"), list)
            or not document["approvals"] or len(document["approvals"]) > MAX_APPROVERS
            or not isinstance(document.get("emergencyRevokedKeyIds"), list)
            or document["emergencyRevokedKeyIds"] != sorted(
                set(document["emergencyRevokedKeyIds"]))):
        raise ValueError("Adapter certifier trust activation report is malformed")
    people: set[str] = set()
    keys: set[str] = set()
    for approval in document["approvals"]:
        if (not isinstance(approval, dict) or set(approval) != {
                "approverId", "keyId", "approvalSha256"
                } or any(package_tool.IDENTIFIER.fullmatch(str(
                    approval.get(name, ""))) is None
                    for name in ("approverId", "keyId"))
                or package_tool.SHA256.fullmatch(str(
                    approval.get("approvalSha256", ""))) is None
                or approval["approverId"] in people or approval["keyId"] in keys):
            raise ValueError("Adapter certifier trust activation approval is malformed")
        people.add(approval["approverId"])
        keys.add(approval["keyId"])
    if (document["proposerId"] in people or document["activatorId"] in people
            or document["proposerId"] == document["activatorId"]
            or any(package_tool.IDENTIFIER.fullmatch(str(item)) is None
                   for item in document["emergencyRevokedKeyIds"])
            or (document["mode"] == "standard"
                and document["emergencyRevokedKeyIds"])):
        raise ValueError("Adapter certifier trust activation separation is malformed")
    package_tool.parse_time(document["activatedAt"], "activation activatedAt")
    if version == 2 and package_tool.SHA256.fullmatch(str(
            document.get("signerReadmissionEvidenceSha256", ""))) is None:
        raise ValueError(
            "Adapter certifier trust signer readmission evidence is malformed"
        )


def _load_policy(path_value: str | Path, expected_sha256: str, label: str) \
        -> tuple[dict[str, Any], Path, bytes, str]:
    result = _pinned(path_value, expected_sha256, label)
    trust_tool.validate_policy(result[0])
    return result


def _emergency_delta(current: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    for field in (
            "schemaVersion", "product", "policyId",
            "maximumAttestationLifetimeSeconds", "allowedCertifiers"):
        if candidate[field] != current[field]:
            raise ValueError(f"emergency revocation cannot change {field}")
    existing = {item["keyId"]: item for item in current["revokedKeys"]}
    incoming = {item["keyId"]: item for item in candidate["revokedKeys"]}
    if any(incoming.get(key_id) != item for key_id, item in existing.items()):
        raise ValueError("emergency revocation cannot remove or rewrite a revocation")
    added = sorted(set(incoming) - set(existing))
    if not added:
        raise ValueError("emergency revocation must add at least one revoked key")
    allowed = {item["keyId"] for item in current["allowedCertifiers"]}
    if not set(added).issubset(allowed):
        raise ValueError("emergency revocation can only revoke an active certifier key")
    return added


def propose_command(args: argparse.Namespace) -> int:
    try:
        governance = _pinned(args.governance_policy,
                             args.expected_governance_policy_sha256,
                             "Adapter certifier governance policy")
        validate_governance(governance[0])
        if governance[0]["policyId"] != args.expected_governance_policy_id:
            raise ValueError("Adapter certifier governance policy identity changed")
        current = _load_policy(args.active_policy, args.expected_current_policy_sha256,
                               "active Adapter certifier trust policy")
        candidate = _load_policy(args.candidate_policy,
                                 args.expected_candidate_policy_sha256,
                                 "candidate Adapter certifier trust policy")
        if (candidate[0]["policyId"] != current[0]["policyId"]
                or candidate[0]["generation"] != current[0]["generation"] + 1):
            raise ValueError("candidate Adapter certifier trust policy is not the exact successor")
        if args.mode == "emergency-revocation":
            _emergency_delta(current[0], candidate[0])
        now = _time(args.issued_at)
        maximum = governance[0]["maxEmergencyLifetimeSeconds" if args.mode ==
                                "emergency-revocation" else "maxStandardLifetimeSeconds"]
        if not 60 <= args.lifetime_seconds <= maximum:
            raise ValueError("Adapter certifier trust proposal lifetime exceeds governance")
        proposal = {
            "schemaVersion": 1, "product": PROPOSAL_PRODUCT,
            "operation": "adapter-certifier-trust-propose",
            "proposalId": str(uuid.uuid4()), "mode": args.mode,
            "trustPolicyId": current[0]["policyId"],
            "currentGeneration": current[0]["generation"],
            "currentPolicySha256": current[3],
            "candidateGeneration": candidate[0]["generation"],
            "candidatePolicySha256": candidate[3],
            "governancePolicyId": governance[0]["policyId"],
            "governancePolicySha256": governance[3],
            "proposerId": args.proposer_id, "ticket": args.ticket,
            "reason": args.reason.strip(), "issuedAt": now.isoformat(),
            "expiresAt": (now + timedelta(seconds=args.lifetime_seconds)).isoformat(),
        }
        validate_proposal(proposal)
        registry_tool.exclusive_bytes(Path(args.output).resolve(),
                                      package_tool.json_bytes(proposal))
        print("PDR_ADAPTER_CERTIFIER_TRUST_PROPOSE_PASS "
              f"proposal={proposal['proposalId']} mode={proposal['mode']} "
              f"generation={proposal['candidateGeneration']}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CERTIFIER_TRUST_CONTROL_ERROR: {error}", file=sys.stderr)
        return 2


def approve_command(args: argparse.Namespace) -> int:
    try:
        proposal = _pinned(args.proposal, args.expected_proposal_sha256,
                           "Adapter certifier trust proposal")
        validate_proposal(proposal[0])
        now = _time(args.verification_time)
        if now >= package_tool.parse_time(proposal[0]["expiresAt"], "proposal expiresAt"):
            raise ValueError("Adapter certifier trust proposal expired")
        approval = approval_tool.sign_governed_approval(
            proposal[2], proposal[3], approver_id=args.approver_id,
            key_id=args.key_id,
            product=APPROVAL_PRODUCT, subject_sha_field="proposalSha256",
            purpose="adapter-certifier-trust-approval",
            private_key_environment=getattr(
                args, "private_key_environment", None),
            signer_config=getattr(args, "signer_config", None),
            expected_signer_config_sha256=getattr(
                args, "expected_signer_config_sha256", None),
            signer_admission_config=getattr(
                args, "signer_admission_config", None),
            expected_signer_admission_config_sha256=getattr(
                args, "expected_signer_admission_config_sha256", None),
            verification_time=now,
        )
        validate_approval(approval)
        registry_tool.exclusive_bytes(Path(args.output).resolve(),
                                      package_tool.json_bytes(approval))
        print("PDR_ADAPTER_CERTIFIER_TRUST_APPROVE_PASS "
              f"proposal={proposal[0]['proposalId']} approver={args.approver_id}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CERTIFIER_TRUST_CONTROL_ERROR: {error}", file=sys.stderr)
        return 2


def _verify_approvals(proposal: tuple[dict[str, Any], Path, bytes, str],
                      governance: dict[str, Any], key_directory: Path,
                      paths: list[str], at: Any,
                      executor_id: str, args: argparse.Namespace) \
        -> tuple[list[dict[str, str]], tuple[dict[str, Any], str] | None]:
    role = proposal[0]["mode"]
    loaded: list[tuple[dict[str, Any], Path, bytes, str]] = []
    for value in paths:
        approval = _load_json(value, "Adapter certifier trust approval")
        validate_approval(approval[0])
        loaded.append(approval)
    minimum = governance["emergencyMinimumApprovals" if role ==
                         "emergency-revocation" else "standardMinimumApprovals"]
    verified = approval_tool.verify_ed25519_quorum(
        subject_content=proposal[2], subject_sha256=proposal[3],
        initiator_id=proposal[0]["proposerId"], executor_id=executor_id,
        required_role=role, minimum_approvals=minimum,
        allowed_approvers=governance["allowedApprovers"],
        allowed_executor_ids=governance["activatorIds"],
        revoked_keys=governance["revokedKeys"], approvals=loaded,
        approval_validator=validate_approval,
        subject_sha_field="proposalSha256",
        trusted_keys_directory=key_directory, verification_time=at,
        external_signer_purpose="adapter-certifier-trust-approval",
    )
    import team_contract_governance_approval_signer_admission \
        as admission_tool
    readmission = admission_tool.enforce_readmission(
        loaded,
        bundle_path=getattr(args, "signer_readmission_bundle", None),
        expected_bundle_sha256=getattr(
            args, "expected_signer_readmission_bundle_sha256", None),
        report_path=getattr(args, "signer_readmission_report", None),
        purpose="adapter-certifier-trust-approval",
        subject_sha256=proposal[3], executor_id=executor_id,
        verification_time=at,
    )
    return verified, readmission


def verify_activation(args: argparse.Namespace) -> tuple[
        tuple[dict[str, Any], Path, bytes, str],
        tuple[dict[str, Any], Path, bytes, str], dict[str, Any]]:
    """Verify an activation completely without committing its candidate."""
    governance = _pinned(args.governance_policy,
                         args.expected_governance_policy_sha256,
                         "Adapter certifier governance policy")
    validate_governance(governance[0])
    if governance[0]["policyId"] != args.expected_governance_policy_id:
        raise ValueError("Adapter certifier governance policy identity changed")
    proposal = _pinned(args.proposal, args.expected_proposal_sha256,
                       "Adapter certifier trust proposal")
    validate_proposal(proposal[0])
    now = _time(args.verification_time)
    issued = package_tool.parse_time(proposal[0]["issuedAt"], "proposal issuedAt")
    expires = package_tool.parse_time(proposal[0]["expiresAt"], "proposal expiresAt")
    maximum = governance[0]["maxEmergencyLifetimeSeconds" if proposal[0]["mode"] ==
                            "emergency-revocation" else "maxStandardLifetimeSeconds"]
    if (issued > now + timedelta(minutes=5) or now >= expires
            or (expires - issued).total_seconds() > maximum
            or proposal[0]["governancePolicyId"] != governance[0]["policyId"]
            or proposal[0]["governancePolicySha256"] != governance[3]):
        raise ValueError("Adapter certifier trust proposal is expired, future or stale")
    current = _load_policy(args.active_policy, args.expected_current_policy_sha256,
                           "active Adapter certifier trust policy")
    candidate = _load_policy(args.candidate_policy,
                             args.expected_candidate_policy_sha256,
                             "candidate Adapter certifier trust policy")
    expected = {
        "trustPolicyId": current[0]["policyId"],
        "currentGeneration": current[0]["generation"],
        "currentPolicySha256": current[3],
        "candidateGeneration": candidate[0]["generation"],
        "candidatePolicySha256": candidate[3],
    }
    if any(proposal[0][name] != value for name, value in expected.items()) \
            or candidate[0]["policyId"] != current[0]["policyId"] \
            or candidate[0]["generation"] != current[0]["generation"] + 1:
        raise ValueError("Adapter certifier trust activation inputs changed")
    added: list[str] = []
    if proposal[0]["mode"] == "emergency-revocation":
        added = _emergency_delta(current[0], candidate[0])
    approvals, readmission = _verify_approvals(
        proposal, governance[0],
        Path(args.trusted_keys_directory).resolve(),
        args.approval, now, args.activator_id, args,
    )
    if (args.activator_id not in governance[0]["activatorIds"]
            or args.activator_id == proposal[0]["proposerId"]
            or args.activator_id in {item["approverId"] for item in approvals}):
        raise ValueError("Adapter certifier trust activator is not allowed or not separated")
    report = {
        "schemaVersion": 2 if readmission else 1,
        "product": PRODUCT + "ActivationReport",
        "passed": True, "proposalId": proposal[0]["proposalId"],
        "mode": proposal[0]["mode"], "trustPolicyId": candidate[0]["policyId"],
        "previousGeneration": current[0]["generation"],
        "previousPolicySha256": current[3],
        "generation": candidate[0]["generation"],
        "policySha256": candidate[3], "governancePolicyId": governance[0]["policyId"],
        "governancePolicySha256": governance[3], "proposerId": proposal[0]["proposerId"],
        "activatorId": args.activator_id, "approvals": approvals,
        "emergencyRevokedKeyIds": added, "activatedAt": now.isoformat(),
    }
    if readmission:
        report["signerReadmissionEvidenceSha256"] = readmission[1]
    validate_activation_report(report)
    return current, candidate, report


def _commit_local(current: tuple[dict[str, Any], Path, bytes, str],
                  candidate: tuple[dict[str, Any], Path, bytes, str],
                  report: dict[str, Any]) -> None:
    active_path = current[1]
    lease = process_lease.ProcessFileLease(
        active_path.with_name(active_path.name + ".write.lock"),
        active_path.with_name(active_path.name + ".write.epoch.json"),
        "adapter-certifier-trust-writer",
        {"operation": report["mode"], "actor": report["activatorId"]},
    )
    try:
        try:
            lease.acquire()
        except process_lease.LeaseBusyError as error:
            raise ValueError(
                "Adapter certifier trust policy is already being modified"
            ) from error
        refreshed = _load_policy(
            active_path, current[3],
            "locked active Adapter certifier trust policy",
        )
        if refreshed[0] != current[0]:
            raise ValueError(
                "active Adapter certifier trust policy changed before commit"
            )
        temporary = active_path.with_name(active_path.name + ".activate.tmp")
        try:
            temporary.write_bytes(candidate[2])
            lease.assert_current()
            os.replace(temporary, active_path)
        finally:
            temporary.unlink(missing_ok=True)
    finally:
        lease.release()


def activate_command(args: argparse.Namespace) -> int:
    try:
        current, candidate, report = verify_activation(args)
        _commit_local(current, candidate, report)
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print("PDR_ADAPTER_CERTIFIER_TRUST_ACTIVATE_PASS "
              f"mode={report['mode']} generation={candidate[0]['generation']} "
              f"approvals={len(report['approvals'])}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CERTIFIER_TRUST_CONTROL_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    propose = commands.add_parser("propose")
    propose.add_argument("--active-policy", required=True)
    propose.add_argument("--expected-current-policy-sha256", required=True)
    propose.add_argument("--candidate-policy", required=True)
    propose.add_argument("--expected-candidate-policy-sha256", required=True)
    propose.add_argument("--governance-policy", required=True)
    propose.add_argument("--expected-governance-policy-id", required=True)
    propose.add_argument("--expected-governance-policy-sha256", required=True)
    propose.add_argument("--mode", choices=("standard", "emergency-revocation"), default="standard")
    propose.add_argument("--proposer-id", required=True)
    propose.add_argument("--ticket", required=True)
    propose.add_argument("--reason", required=True)
    propose.add_argument("--issued-at")
    propose.add_argument("--lifetime-seconds", type=int, default=3600)
    propose.add_argument("--output", required=True)
    propose.set_defaults(handler=propose_command)
    approve = commands.add_parser("approve")
    approve.add_argument("--proposal", required=True)
    approve.add_argument("--expected-proposal-sha256", required=True)
    approve.add_argument("--approver-id", required=True)
    approve.add_argument("--key-id", required=True)
    approve.add_argument("--private-key-environment")
    approve.add_argument("--signer-config")
    approve.add_argument("--expected-signer-config-sha256")
    approve.add_argument("--signer-admission-config")
    approve.add_argument("--expected-signer-admission-config-sha256")
    approve.add_argument("--verification-time")
    approve.add_argument("--output", required=True)
    approve.set_defaults(handler=approve_command)
    activate = commands.add_parser("activate")
    activate.add_argument("--active-policy", required=True)
    activate.add_argument("--expected-current-policy-sha256", required=True)
    activate.add_argument("--candidate-policy", required=True)
    activate.add_argument("--expected-candidate-policy-sha256", required=True)
    activate.add_argument("--proposal", required=True)
    activate.add_argument("--expected-proposal-sha256", required=True)
    activate.add_argument("--approval", action="append", required=True)
    activate.add_argument("--governance-policy", required=True)
    activate.add_argument("--expected-governance-policy-id", required=True)
    activate.add_argument("--expected-governance-policy-sha256", required=True)
    activate.add_argument("--trusted-keys-directory", required=True)
    activate.add_argument("--activator-id", required=True)
    activate.add_argument("--verification-time")
    activate.add_argument("--signer-readmission-bundle")
    activate.add_argument("--expected-signer-readmission-bundle-sha256")
    activate.add_argument("--signer-readmission-report")
    activate.add_argument("--report")
    activate.set_defaults(handler=activate_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
