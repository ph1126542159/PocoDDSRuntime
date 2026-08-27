#!/usr/bin/env python3
"""Portable M-of-N Ed25519 governance approval protocol and verification engine."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

import team_contract_package as package_tool
import team_contract_registry as registry_tool


PRODUCT = "PocoDDSRuntimeTeamContractGovernanceApproval"
POLICY_PRODUCT = PRODUCT + "Policy"
SUBJECT_PRODUCT = PRODUCT + "Subject"
APPROVAL_PRODUCT = PRODUCT + "Signature"
EVIDENCE_PRODUCT = PRODUCT + "Evidence"
SIGNING_PAYLOAD_PRODUCT = PRODUCT + "SigningPayload"
MAX_APPROVERS = 64
MAX_ROLES = 32
MAX_LIFETIME = 86400

LoadedDocument = tuple[dict[str, Any], Path, bytes, str]
SIGNER_DESCRIPTOR_FIELDS = {
    "signerId", "signerConfigSha256",
    "signerCapabilityManifestSha256",
}
SIGNER_ADMISSION_FIELDS = {
    "signerConformanceId", "signerConformanceEvidenceSha256",
    "signerConformanceAttestationSha256",
    "signerConformanceCertifierId", "signerConformanceCertifierKeyId",
    "signerConformanceTrustPolicyId",
    "signerConformanceTrustPolicyGeneration",
    "signerConformanceTrustPolicySha256",
}


def _identity(value: Any, label: str) -> str:
    result = str(value)
    if package_tool.IDENTIFIER.fullmatch(result) is None:
        raise ValueError(f"Governance approval {label} is malformed")
    return result


def _sha(value: Any, label: str) -> str:
    result = str(value).lower()
    if package_tool.SHA256.fullmatch(result) is None:
        raise ValueError(f"Governance approval {label} is malformed")
    return result


def validate_signer_descriptor(document: Any, *, admitted: bool) -> None:
    fields = SIGNER_DESCRIPTOR_FIELDS | (
        SIGNER_ADMISSION_FIELDS if admitted else set()
    )
    if not isinstance(document, dict) or not fields.issubset(document):
        raise ValueError("Governance approval signer descriptor is malformed")
    _identity(document.get("signerId"), "signer identity")
    for name in (
            "signerConfigSha256", "signerCapabilityManifestSha256"):
        _sha(document.get(name), name)
    if admitted:
        for name in (
                "signerConformanceCertifierId",
                "signerConformanceCertifierKeyId",
                "signerConformanceTrustPolicyId"):
            _identity(document.get(name), name)
        for name in (
                "signerConformanceId",
                "signerConformanceEvidenceSha256",
                "signerConformanceAttestationSha256",
                "signerConformanceTrustPolicySha256"):
            _sha(document.get(name), name)
        generation = document.get(
            "signerConformanceTrustPolicyGeneration"
        )
        if type(generation) is not int or not 1 <= generation <= 2147483647:
            raise ValueError(
                "Governance approval signer trust generation is malformed"
            )


def validate_policy(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "policyId", "roles",
        "allowedApprovers", "executorIds", "revokedKeys",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != POLICY_PRODUCT):
        raise ValueError("Governance approval policy is malformed")
    _identity(document.get("policyId"), "policy identity")
    roles = document.get("roles")
    if (not isinstance(roles, list) or not 1 <= len(roles) <= MAX_ROLES):
        raise ValueError("Governance approval roles are malformed")
    role_ids: set[str] = set()
    for item in roles:
        if (not isinstance(item, dict) or set(item) != {
                "roleId", "minimumApprovals", "maxSubjectLifetimeSeconds"
                }):
            raise ValueError("Governance approval role is malformed")
        role_id = _identity(item.get("roleId"), "role identity")
        minimum = item.get("minimumApprovals")
        lifetime = item.get("maxSubjectLifetimeSeconds")
        if (role_id in role_ids or type(minimum) is not int
                or not 1 <= minimum <= MAX_APPROVERS
                or type(lifetime) is not int
                or not 60 <= lifetime <= MAX_LIFETIME):
            raise ValueError("Governance approval role is malformed")
        role_ids.add(role_id)
    if [item["roleId"] for item in roles] != sorted(role_ids):
        raise ValueError("Governance approval roles must be sorted")
    approvers = document.get("allowedApprovers")
    if (not isinstance(approvers, list) or not 1 <= len(approvers) <= MAX_APPROVERS):
        raise ValueError("Governance approval approvers are malformed")
    people: set[str] = set()
    keys: set[str] = set()
    for item in approvers:
        if (not isinstance(item, dict) or set(item) != {
                "approverId", "keyId", "algorithm", "publicKeySha256", "roles"
                } or item.get("algorithm") != "Ed25519"):
            raise ValueError("Governance approval approver is malformed")
        person = _identity(item.get("approverId"), "approver identity")
        key_id = _identity(item.get("keyId"), "key identity")
        _sha(item.get("publicKeySha256"), "public key SHA")
        item_roles = item.get("roles")
        if (person in people or key_id in keys
                or not isinstance(item_roles, list) or not item_roles
                or item_roles != sorted(set(item_roles))
                or not set(item_roles).issubset(role_ids)):
            raise ValueError("Governance approval approver is malformed")
        people.add(person)
        keys.add(key_id)
    for rule in roles:
        eligible = [item for item in approvers if rule["roleId"] in item["roles"]]
        if (len({item["approverId"] for item in eligible})
                < rule["minimumApprovals"]
                or len({item["keyId"] for item in eligible})
                < rule["minimumApprovals"]):
            raise ValueError("Governance approval quorum is impossible")
    executors = document.get("executorIds")
    if (not isinstance(executors, list) or not executors
            or executors != sorted(set(executors))
            or len(executors) > MAX_APPROVERS):
        raise ValueError("Governance approval executors are malformed")
    for value in executors:
        _identity(value, "executor identity")
    revoked = document.get("revokedKeys")
    if not isinstance(revoked, list) or len(revoked) > MAX_APPROVERS:
        raise ValueError("Governance approval revocations are malformed")
    revoked_ids: set[str] = set()
    for item in revoked:
        if (not isinstance(item, dict) or set(item) != {
                "keyId", "revokedAt", "reason"
                } or not isinstance(item.get("reason"), str)
                or not item["reason"].strip() or len(item["reason"]) > 512):
            raise ValueError("Governance approval revocation is malformed")
        key_id = _identity(item.get("keyId"), "revoked key identity")
        if key_id in revoked_ids:
            raise ValueError("Governance approval revocation is duplicated")
        package_tool.parse_time(item["revokedAt"], "governance revokedAt")
        revoked_ids.add(key_id)


def validate_subject(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "subjectId", "subjectType", "role",
        "payloadProduct", "payloadSha256", "policyId", "policySha256",
        "initiatorId", "reason", "issuedAt", "expiresAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != SUBJECT_PRODUCT
            or not isinstance(document.get("reason"), str)
            or not document["reason"].strip() or len(document["reason"]) > 512):
        raise ValueError("Governance approval subject is malformed")
    for name in (
            "subjectId", "subjectType", "role", "payloadProduct", "policyId",
            "initiatorId"):
        _identity(document.get(name), name)
    _sha(document.get("payloadSha256"), "payload SHA")
    _sha(document.get("policySha256"), "policy SHA")
    issued = package_tool.parse_time(document["issuedAt"], "subject issuedAt")
    expires = package_tool.parse_time(document["expiresAt"], "subject expiresAt")
    if issued >= expires:
        raise ValueError("Governance approval subject lifetime is malformed")


def validate_approval(document: Any) -> None:
    base_fields = {
            "schemaVersion", "product", "algorithm", "approverId", "keyId",
            "subjectId", "subjectSha256", "signature"
    }
    version = document.get("schemaVersion") if isinstance(document, dict) else None
    fields = base_fields | (
        SIGNER_DESCRIPTOR_FIELDS if version == 2 else
        SIGNER_DESCRIPTOR_FIELDS | SIGNER_ADMISSION_FIELDS
        if version == 3 else set()
    )
    if (not isinstance(document, dict) or set(document) != fields
            or version not in {1, 2, 3}
            or document.get("product") != APPROVAL_PRODUCT
            or document.get("algorithm") != "Ed25519"):
        raise ValueError("Governance approval signature is malformed")
    for name in ("approverId", "keyId", "subjectId"):
        _identity(document.get(name), name)
    _sha(document.get("subjectSha256"), "subject SHA")
    try:
        signature = base64.b64decode(document["signature"], validate=True)
    except (TypeError, ValueError) as error:
        raise ValueError("Governance approval signature is malformed") from error
    if len(signature) != 64:
        raise ValueError("Governance approval signature is malformed")
    if version in {2, 3}:
        validate_signer_descriptor(document, admitted=version == 3)


def _approval_summary(document: Any) -> None:
    if (not isinstance(document, dict) or set(document) != {
            "approverId", "keyId", "approvalSha256"
            }):
        raise ValueError("Governance approval evidence entry is malformed")
    _identity(document.get("approverId"), "approver identity")
    _identity(document.get("keyId"), "key identity")
    _sha(document.get("approvalSha256"), "approval SHA")


def validate_evidence(document: Any) -> None:
    base_fields = {
        "schemaVersion", "product", "passed", "subjectId", "subjectType",
        "subjectSha256", "payloadProduct", "payloadSha256", "role",
        "policyId", "policySha256", "initiatorId", "executorId",
        "minimumApprovals", "approvals", "verifiedAt",
    }
    version = document.get("schemaVersion") if isinstance(document, dict) else None
    fields = base_fields | (
        {"signerReadmissionEvidenceSha256"} if version == 2 else set()
    )
    if (not isinstance(document, dict) or set(document) != fields
            or version not in {1, 2}
            or document.get("product") != EVIDENCE_PRODUCT
            or document.get("passed") is not True
            or type(document.get("minimumApprovals")) is not int
            or not 1 <= document["minimumApprovals"] <= MAX_APPROVERS
            or not isinstance(document.get("approvals"), list)
            or len(document["approvals"]) < document["minimumApprovals"]
            or len(document["approvals"]) > MAX_APPROVERS):
        raise ValueError("Governance approval evidence is malformed")
    for name in (
            "subjectId", "subjectType", "payloadProduct", "role", "policyId",
            "initiatorId", "executorId"):
        _identity(document.get(name), name)
    for name in ("subjectSha256", "payloadSha256", "policySha256"):
        _sha(document.get(name), name)
    if version == 2:
        _sha(document.get("signerReadmissionEvidenceSha256"),
             "signer readmission evidence SHA")
    people: set[str] = set()
    keys: set[str] = set()
    for item in document["approvals"]:
        _approval_summary(item)
        if item["approverId"] in people or item["keyId"] in keys:
            raise ValueError("Governance approval evidence is duplicated")
        people.add(item["approverId"])
        keys.add(item["keyId"])
    if (document["initiatorId"] == document["executorId"]
            or document["initiatorId"] in people
            or document["executorId"] in people):
        raise ValueError("Governance approval evidence duties are not separated")
    package_tool.parse_time(document["verifiedAt"], "approval verifiedAt")


def load_pinned_document(path_value: str | Path, expected_sha256: str,
                         label: str, validator: Callable[[Any], None]) \
        -> LoadedDocument:
    path = package_tool.resolved_path(path_value, label)
    content = path.read_bytes()
    digest = package_tool.sha256_bytes(content)
    if _sha(expected_sha256, f"{label} expected SHA") != digest:
        raise ValueError(f"{label} SHA changed")
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON") from error
    validator(document)
    return document, path, content, digest


def sign_ed25519_document(
        subject_content: bytes, subject_sha256: str, *, approver_id: str,
        key_id: str, private_key_environment: str, product: str,
        subject_sha_field: str, extra_fields: dict[str, Any] | None = None) \
        -> dict[str, Any]:
    _sha(subject_sha256, "subject SHA")
    if package_tool.sha256_bytes(subject_content) != subject_sha256:
        raise ValueError("Governance approval subject bytes changed")
    _identity(approver_id, "approver identity")
    _identity(key_id, "key identity")
    key_value = os.environ.get(private_key_environment)
    if not key_value:
        raise ValueError("Governance approval private key environment is unset")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key = load_pem_private_key(
            Path(key_value).resolve().read_bytes(), password=None
        )
    except ImportError as error:
        raise ValueError("Governance approval requires cryptography") from error
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Governance approval private key is not Ed25519")
    result = {
        "schemaVersion": 1, "product": product, "algorithm": "Ed25519",
        "approverId": approver_id, "keyId": key_id,
        subject_sha_field: subject_sha256,
        "signature": base64.b64encode(key.sign(subject_content)).decode("ascii"),
    }
    if extra_fields:
        result.update(extra_fields)
    return result


def sign_governed_approval(
        subject_content: bytes, subject_sha256: str, *, approver_id: str,
        key_id: str, product: str, subject_sha_field: str, purpose: str,
        private_key_environment: str | None = None,
        signer_config: str | None = None,
        expected_signer_config_sha256: str | None = None,
        signer_admission_config: str | None = None,
        expected_signer_admission_config_sha256: str | None = None,
        verification_time: Any = None,
        extra_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    local = private_key_environment is not None
    external = signer_config is not None or expected_signer_config_sha256 is not None
    if local == external:
        raise ValueError(
            "Governance approval requires exactly one local or external signer mode"
        )
    admission_values = (
        signer_admission_config,
        expected_signer_admission_config_sha256,
    )
    admitted = any(value is not None for value in admission_values)
    if admitted and (local or not all(admission_values)):
        raise ValueError(
            "Governance approval signer admission requires complete external mode"
        )
    if local:
        assert private_key_environment is not None
        return sign_ed25519_document(
            subject_content, subject_sha256, approver_id=approver_id,
            key_id=key_id,
            private_key_environment=private_key_environment,
            product=product, subject_sha_field=subject_sha_field,
            extra_fields=extra_fields,
        )
    if signer_config is None or expected_signer_config_sha256 is None:
        raise ValueError("Governance approval signer configuration is incomplete")
    import team_contract_governance_approval_signer as signer_tool
    signer = signer_tool.ExternalCommandGovernanceApprovalSigner(
        signer_config, expected_signer_config_sha256
    )
    if signer.approver_id != approver_id:
        raise ValueError("Governance approval signer approver identity changed")
    descriptor = signer.descriptor()
    if admitted:
        import team_contract_governance_approval_signer_admission \
            as admission_tool
        assert signer_admission_config is not None
        assert expected_signer_admission_config_sha256 is not None
        descriptor.update(admission_tool.admit(
            signer_admission_config,
            expected_signer_admission_config_sha256,
            signer=signer, verification_time=verification_time,
        ))
    signing_payload = external_signing_payload(
        purpose=purpose, approval_product=product,
        approver_id=approver_id, key_id=key_id,
        subject_sha256=subject_sha256, descriptor=descriptor,
    )
    signature = signer.sign(signing_payload, key_id, purpose)
    result = {
        "schemaVersion": 3 if admitted else 2,
        "product": product, "algorithm": "Ed25519",
        "approverId": approver_id, "keyId": key_id,
        subject_sha_field: subject_sha256,
        "signature": base64.b64encode(signature).decode("ascii"),
        **descriptor,
    }
    if extra_fields:
        result.update(extra_fields)
    return result


def external_signing_payload(
        *, purpose: str, approval_product: str, approver_id: str,
        key_id: str, subject_sha256: str,
        descriptor: dict[str, Any]) -> bytes:
    if purpose not in {
            "governance-approval", "adapter-certifier-trust-approval",
            "adapter-certifier-trust-migration-approval"}:
        raise ValueError("Governance approval signer purpose is malformed")
    _identity(approval_product, "approval product")
    _identity(approver_id, "approver identity")
    _identity(key_id, "key identity")
    _sha(subject_sha256, "subject SHA")
    admitted = isinstance(descriptor, dict) and \
        set(descriptor) == SIGNER_DESCRIPTOR_FIELDS | SIGNER_ADMISSION_FIELDS
    if (not isinstance(descriptor, dict)
            or set(descriptor) not in (
                SIGNER_DESCRIPTOR_FIELDS,
                SIGNER_DESCRIPTOR_FIELDS | SIGNER_ADMISSION_FIELDS,
            )):
        raise ValueError("Governance approval signer descriptor is malformed")
    validate_signer_descriptor(descriptor, admitted=admitted)
    payload = {
        "schemaVersion": 2 if admitted else 1,
        "product": SIGNING_PAYLOAD_PRODUCT,
        "purpose": purpose, "approvalProduct": approval_product,
        "approverId": approver_id, "keyId": key_id,
        "subjectSha256": subject_sha256,
        # Keep the byte-level v1 contract stable and make the v2 order
        # independent of set/dict construction in callers. json_bytes() is
        # intentionally deterministic by insertion order rather than by
        # sorting keys because existing external signers sign these bytes.
        "signerId": descriptor["signerId"],
        "signerConfigSha256": descriptor["signerConfigSha256"],
        "signerCapabilityManifestSha256":
            descriptor["signerCapabilityManifestSha256"],
    }
    if admitted:
        for name in (
                "signerConformanceId",
                "signerConformanceEvidenceSha256",
                "signerConformanceAttestationSha256",
                "signerConformanceCertifierId",
                "signerConformanceCertifierKeyId",
                "signerConformanceTrustPolicyId",
                "signerConformanceTrustPolicyGeneration",
                "signerConformanceTrustPolicySha256"):
            payload[name] = descriptor[name]
    return package_tool.json_bytes(payload)


def verify_ed25519_quorum(
        *, subject_content: bytes, subject_sha256: str, initiator_id: str,
        executor_id: str, required_role: str, minimum_approvals: int,
        allowed_approvers: list[dict[str, Any]], allowed_executor_ids: Iterable[str],
        revoked_keys: list[dict[str, Any]], approvals: list[LoadedDocument],
        approval_validator: Callable[[Any], None], subject_sha_field: str,
        trusted_keys_directory: str | Path, verification_time: Any,
        external_signer_purpose: str | None = None) \
        -> list[dict[str, str]]:
    if package_tool.sha256_bytes(subject_content) != _sha(
            subject_sha256, "subject SHA"):
        raise ValueError("Governance approval subject bytes changed")
    _identity(initiator_id, "initiator identity")
    _identity(executor_id, "executor identity")
    _identity(required_role, "role identity")
    if type(minimum_approvals) is not int \
            or not 1 <= minimum_approvals <= MAX_APPROVERS:
        raise ValueError("Governance approval threshold is malformed")
    executors = set(allowed_executor_ids)
    if executor_id not in executors or initiator_id == executor_id:
        raise ValueError("Governance approval executor is not allowed or separated")
    key_directory = Path(trusted_keys_directory).resolve()
    if not key_directory.is_dir():
        raise ValueError("Governance approval key directory is unavailable")
    at = verification_time
    revoked = {
        item["keyId"] for item in revoked_keys
        if at >= package_tool.parse_time(item["revokedAt"], "approval revokedAt")
    }
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    except ImportError as error:
        raise ValueError("Governance approval requires cryptography") from error
    people: set[str] = set()
    keys: set[str] = set()
    results: list[dict[str, str]] = []
    for approval in approvals:
        approval_validator(approval[0])
        approver_id = _identity(approval[0].get("approverId"), "approver identity")
        key_id = _identity(approval[0].get("keyId"), "key identity")
        if (approval[0].get(subject_sha_field) != subject_sha256
                or approver_id in people or key_id in keys
                or approver_id in {initiator_id, executor_id} or key_id in revoked):
            raise ValueError("Governance approval is stale, duplicated, revoked or unseparated")
        matches = [
            item for item in allowed_approvers
            if item.get("approverId") == approver_id
            and item.get("keyId") == key_id
            and item.get("algorithm") == "Ed25519"
            and required_role in item.get("roles", [])
        ]
        if len(matches) != 1:
            raise ValueError("Governance approver is not allowed for this role")
        key_path = (key_directory / f"{key_id}.pem").resolve()
        if key_path.parent != key_directory or not key_path.is_file():
            raise ValueError("Governance approval public key is unavailable")
        key_bytes = key_path.read_bytes()
        if package_tool.sha256_bytes(key_bytes) != matches[0].get("publicKeySha256"):
            raise ValueError("Governance approval public key SHA changed")
        try:
            key = load_pem_public_key(key_bytes)
            if not isinstance(key, Ed25519PublicKey):
                raise ValueError("approval key is not Ed25519")
            signed_content = subject_content
            if approval[0]["schemaVersion"] in {2, 3}:
                if external_signer_purpose is None:
                    raise ValueError(
                        "Governance approval external signer purpose is required"
                    )
                signed_content = external_signing_payload(
                    purpose=external_signer_purpose,
                    approval_product=approval[0]["product"],
                    approver_id=approver_id, key_id=key_id,
                    subject_sha256=subject_sha256,
                    descriptor={
                        name: approval[0][name]
                        for name in SIGNER_DESCRIPTOR_FIELDS | (
                            SIGNER_ADMISSION_FIELDS
                            if approval[0]["schemaVersion"] == 3 else set()
                        )
                    },
                )
            key.verify(
                base64.b64decode(approval[0]["signature"], validate=True),
                signed_content,
            )
        except Exception as error:
            raise ValueError("Governance approval signature failed") from error
        people.add(approver_id)
        keys.add(key_id)
        results.append({
            "approverId": approver_id, "keyId": key_id,
            "approvalSha256": approval[3],
        })
    if len(results) < minimum_approvals:
        raise ValueError(
            f"Governance approval quorum not met: "
            f"{len(results)}/{minimum_approvals}"
        )
    return sorted(results, key=lambda item: (item["approverId"], item["keyId"]))


def _payload(path_value: str, expected_sha256: str,
             expected_product: str) -> LoadedDocument:
    def validate(document: Any) -> None:
        if not isinstance(document, dict) or document.get("product") != expected_product:
            raise ValueError("Governance approval payload product changed")
    return load_pinned_document(
        path_value, expected_sha256, "Governance approval payload", validate
    )


def subject_command(args: argparse.Namespace) -> int:
    try:
        payload = _payload(
            args.payload, args.expected_payload_sha256,
            args.expected_payload_product,
        )
        policy = load_pinned_document(
            args.policy, args.expected_policy_sha256,
            "Governance approval policy", validate_policy,
        )
        if policy[0]["policyId"] != args.expected_policy_id:
            raise ValueError("Governance approval policy identity changed")
        matches = [item for item in policy[0]["roles"] if item["roleId"] == args.role]
        if len(matches) != 1:
            raise ValueError("Governance approval role is unavailable")
        if not 60 <= args.lifetime_seconds <= matches[0]["maxSubjectLifetimeSeconds"]:
            raise ValueError("Governance approval subject lifetime exceeds policy")
        now = package_tool.verification_time(args.issued_at)
        subject = {
            "schemaVersion": 1, "product": SUBJECT_PRODUCT,
            "subjectId": args.subject_id or str(uuid.uuid4()),
            "subjectType": args.subject_type, "role": args.role,
            "payloadProduct": args.expected_payload_product,
            "payloadSha256": payload[3], "policyId": policy[0]["policyId"],
            "policySha256": policy[3], "initiatorId": args.initiator_id,
            "reason": args.reason.strip(), "issuedAt": now.isoformat(),
            "expiresAt": (now + timedelta(
                seconds=args.lifetime_seconds)).isoformat(),
        }
        validate_subject(subject)
        registry_tool.exclusive_bytes(
            Path(args.output).resolve(), package_tool.json_bytes(subject)
        )
        print("PDR_GOVERNANCE_APPROVAL_SUBJECT_PASS "
              f"subject={subject['subjectId']} role={subject['role']}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_GOVERNANCE_APPROVAL_ERROR: {error}", file=sys.stderr)
        return 2


def approve_command(args: argparse.Namespace) -> int:
    try:
        subject = load_pinned_document(
            args.subject, args.expected_subject_sha256,
            "Governance approval subject", validate_subject,
        )
        now = package_tool.verification_time(args.verification_time)
        if now >= package_tool.parse_time(subject[0]["expiresAt"], "subject expiresAt"):
            raise ValueError("Governance approval subject expired")
        approval = sign_governed_approval(
            subject[2], subject[3], approver_id=args.approver_id,
            key_id=args.key_id,
            product=APPROVAL_PRODUCT, subject_sha_field="subjectSha256",
            purpose="governance-approval",
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
            extra_fields={"subjectId": subject[0]["subjectId"]},
        )
        validate_approval(approval)
        registry_tool.exclusive_bytes(
            Path(args.output).resolve(), package_tool.json_bytes(approval)
        )
        print("PDR_GOVERNANCE_APPROVAL_SIGN_PASS "
              f"subject={subject[0]['subjectId']} approver={args.approver_id}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_GOVERNANCE_APPROVAL_ERROR: {error}", file=sys.stderr)
        return 2


def verify_command(args: argparse.Namespace) -> int:
    try:
        subject = load_pinned_document(
            args.subject, args.expected_subject_sha256,
            "Governance approval subject", validate_subject,
        )
        payload = _payload(
            args.payload, args.expected_payload_sha256,
            subject[0]["payloadProduct"],
        )
        policy = load_pinned_document(
            args.policy, args.expected_policy_sha256,
            "Governance approval policy", validate_policy,
        )
        if (policy[0]["policyId"] != args.expected_policy_id
                or subject[0]["policyId"] != policy[0]["policyId"]
                or subject[0]["policySha256"] != policy[3]
                or subject[0]["payloadSha256"] != payload[3]):
            raise ValueError("Governance approval subject inputs changed")
        now = package_tool.verification_time(args.verification_time)
        issued = package_tool.parse_time(subject[0]["issuedAt"], "subject issuedAt")
        expires = package_tool.parse_time(subject[0]["expiresAt"], "subject expiresAt")
        rules = [
            item for item in policy[0]["roles"]
            if item["roleId"] == subject[0]["role"]
        ]
        if (len(rules) != 1 or issued > now + timedelta(minutes=5) or now >= expires
                or (expires - issued).total_seconds()
                    > rules[0]["maxSubjectLifetimeSeconds"]):
            raise ValueError("Governance approval subject is expired, future or stale")
        loaded_approvals = [
            load_pinned_document(
                path, package_tool.sha256_bytes(Path(path).resolve().read_bytes()),
                "Governance approval signature", validate_approval,
            ) for path in args.approval
        ]
        for approval in loaded_approvals:
            if approval[0]["subjectId"] != subject[0]["subjectId"]:
                raise ValueError("Governance approval subject identity changed")
        approvals = verify_ed25519_quorum(
            subject_content=subject[2], subject_sha256=subject[3],
            initiator_id=subject[0]["initiatorId"], executor_id=args.executor_id,
            required_role=subject[0]["role"],
            minimum_approvals=rules[0]["minimumApprovals"],
            allowed_approvers=policy[0]["allowedApprovers"],
            allowed_executor_ids=policy[0]["executorIds"],
            revoked_keys=policy[0]["revokedKeys"], approvals=loaded_approvals,
            approval_validator=validate_approval,
            subject_sha_field="subjectSha256",
            trusted_keys_directory=args.trusted_keys_directory,
            verification_time=now,
            external_signer_purpose="governance-approval",
        )
        import team_contract_governance_approval_signer_admission \
            as admission_tool
        readmission = admission_tool.enforce_readmission(
            loaded_approvals,
            bundle_path=getattr(args, "signer_readmission_bundle", None),
            expected_bundle_sha256=getattr(
                args, "expected_signer_readmission_bundle_sha256", None),
            report_path=getattr(args, "signer_readmission_report", None),
            purpose="governance-approval", subject_sha256=subject[3],
            executor_id=args.executor_id, verification_time=now,
        )
        evidence = {
            "schemaVersion": 2 if readmission else 1,
            "product": EVIDENCE_PRODUCT, "passed": True,
            "subjectId": subject[0]["subjectId"],
            "subjectType": subject[0]["subjectType"],
            "subjectSha256": subject[3],
            "payloadProduct": subject[0]["payloadProduct"],
            "payloadSha256": payload[3], "role": subject[0]["role"],
            "policyId": policy[0]["policyId"], "policySha256": policy[3],
            "initiatorId": subject[0]["initiatorId"],
            "executorId": args.executor_id,
            "minimumApprovals": rules[0]["minimumApprovals"],
            "approvals": approvals, "verifiedAt": now.isoformat(),
        }
        if readmission:
            evidence["signerReadmissionEvidenceSha256"] = readmission[1]
        validate_evidence(evidence)
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), evidence)
        print("PDR_GOVERNANCE_APPROVAL_VERIFY_PASS "
              f"subject={evidence['subjectId']} approvals={len(approvals)}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_GOVERNANCE_APPROVAL_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    subject = commands.add_parser("subject")
    subject.add_argument("--payload", required=True)
    subject.add_argument("--expected-payload-sha256", required=True)
    subject.add_argument("--expected-payload-product", required=True)
    subject.add_argument("--policy", required=True)
    subject.add_argument("--expected-policy-id", required=True)
    subject.add_argument("--expected-policy-sha256", required=True)
    subject.add_argument("--subject-id")
    subject.add_argument("--subject-type", required=True)
    subject.add_argument("--role", required=True)
    subject.add_argument("--initiator-id", required=True)
    subject.add_argument("--reason", required=True)
    subject.add_argument("--issued-at")
    subject.add_argument("--lifetime-seconds", type=int, default=3600)
    subject.add_argument("--output", required=True)
    subject.set_defaults(handler=subject_command)
    approve = commands.add_parser("approve")
    approve.add_argument("--subject", required=True)
    approve.add_argument("--expected-subject-sha256", required=True)
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
    verify = commands.add_parser("verify")
    verify.add_argument("--subject", required=True)
    verify.add_argument("--expected-subject-sha256", required=True)
    verify.add_argument("--payload", required=True)
    verify.add_argument("--expected-payload-sha256", required=True)
    verify.add_argument("--policy", required=True)
    verify.add_argument("--expected-policy-id", required=True)
    verify.add_argument("--expected-policy-sha256", required=True)
    verify.add_argument("--approval", action="append", required=True)
    verify.add_argument("--trusted-keys-directory", required=True)
    verify.add_argument("--executor-id", required=True)
    verify.add_argument("--verification-time")
    verify.add_argument("--signer-readmission-bundle")
    verify.add_argument("--expected-signer-readmission-bundle-sha256")
    verify.add_argument("--signer-readmission-report")
    verify.add_argument("--report")
    verify.set_defaults(handler=verify_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
