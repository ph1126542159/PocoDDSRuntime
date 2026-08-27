#!/usr/bin/env python3
"""Portable Governance Approval engine and protocol fault-injection tests."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import team_contract_governance_approval as approval_tool
import team_contract_adapter_certifier_trust_control as trust_control
import team_contract_adapter_certifier_trust_state_store as trust_state
import team_contract_package as package_tool


NOW = "2026-08-27T12:00:00+00:00"


def write_json(path: Path, document: dict) -> str:
    path.write_bytes(package_tool.json_bytes(document))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key_pair(directory: Path, identity: str) -> tuple[Path, str]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )
    key = Ed25519PrivateKey.generate()
    private = directory / f"{identity}.private.pem"
    public = directory / f"{identity}.pem"
    private.write_bytes(key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ))
    public.write_bytes(key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    ))
    return private, hashlib.sha256(public.read_bytes()).hexdigest()


class GovernanceApprovalTest(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("PDR_GOVERNANCE_APPROVAL_KEY", None)

    def test_payload_bound_quorum_roles_revocation_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            keys = root / "keys"
            keys.mkdir()
            material: dict[str, tuple[Path, str]] = {}
            for key_id in ("approval-key-a", "approval-key-b", "approval-key-c"):
                material[key_id] = key_pair(keys, key_id)
            policy = {
                "schemaVersion": 1, "product": approval_tool.POLICY_PRODUCT,
                "policyId": "production-governance",
                "roles": [{
                    "roleId": "production-change", "minimumApprovals": 2,
                    "maxSubjectLifetimeSeconds": 3600,
                }],
                "allowedApprovers": [
                    {"approverId": person, "keyId": key_id,
                     "algorithm": "Ed25519",
                     "publicKeySha256": material[key_id][1],
                     "roles": ["production-change"]}
                    for person, key_id in (
                        ("security-a", "approval-key-a"),
                        ("security-b", "approval-key-b"),
                        ("security-c", "approval-key-c"),
                    )
                ], "executorIds": ["release-operator"], "revokedKeys": [],
            }
            policy_path = root / "policy.json"
            policy_sha = write_json(policy_path, policy)
            approval_tool.validate_policy(policy)
            payload_path = root / "payload.json"
            payload = {
                "schemaVersion": 1, "product": "ExampleProductionChange",
                "changeId": "change-42", "candidateSha256": "a" * 64,
            }
            payload_sha = write_json(payload_path, payload)
            subject_path = root / "subject.json"
            self.assertEqual(approval_tool.subject_command(Namespace(
                payload=str(payload_path), expected_payload_sha256=payload_sha,
                expected_payload_product="ExampleProductionChange",
                policy=str(policy_path), expected_policy_id="production-governance",
                expected_policy_sha256=policy_sha, subject_id="change-42-approval",
                subject_type="production-change-request",
                role="production-change", initiator_id="release-author",
                reason="approve production change 42", issued_at=NOW,
                lifetime_seconds=3600, output=str(subject_path),
            )), 0)
            subject_sha = hashlib.sha256(subject_path.read_bytes()).hexdigest()
            subject = json.loads(subject_path.read_bytes())
            approval_tool.validate_subject(subject)
            approvals: list[Path] = []
            for person, key_id in (
                    ("security-a", "approval-key-a"),
                    ("security-b", "approval-key-b")):
                output = root / f"{person}.approval.json"
                os.environ["PDR_GOVERNANCE_APPROVAL_KEY"] = str(material[key_id][0])
                self.assertEqual(approval_tool.approve_command(Namespace(
                    subject=str(subject_path), expected_subject_sha256=subject_sha,
                    approver_id=person, key_id=key_id,
                    private_key_environment="PDR_GOVERNANCE_APPROVAL_KEY",
                    verification_time=NOW, output=str(output),
                )), 0)
                approvals.append(output)
            os.environ.pop("PDR_GOVERNANCE_APPROVAL_KEY", None)

            common = dict(
                subject=str(subject_path), expected_subject_sha256=subject_sha,
                payload=str(payload_path), expected_payload_sha256=payload_sha,
                policy=str(policy_path), expected_policy_id="production-governance",
                expected_policy_sha256=policy_sha,
                trusted_keys_directory=str(keys), executor_id="release-operator",
                verification_time=NOW, report=str(root / "evidence.json"),
            )
            self.assertEqual(approval_tool.verify_command(Namespace(
                **common, approval=[str(approvals[0])]
            )), 2)
            self.assertEqual(approval_tool.verify_command(Namespace(
                **common, approval=[str(path) for path in approvals]
            )), 0)
            evidence = json.loads((root / "evidence.json").read_bytes())
            approval_tool.validate_evidence(evidence)
            self.assertEqual(evidence["minimumApprovals"], 2)
            self.assertEqual(len(evidence["approvals"]), 2)
            serialized = json.dumps(evidence, sort_keys=True)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("private", serialized.lower())

            self.assertEqual(approval_tool.verify_command(Namespace(
                **common, approval=[str(approvals[0]), str(approvals[0])]
            )), 2)
            separated = dict(common, executor_id="security-a")
            self.assertEqual(approval_tool.verify_command(Namespace(
                **separated, approval=[str(path) for path in approvals]
            )), 2)
            expired = dict(common, verification_time="2026-08-27T14:00:00+00:00")
            self.assertEqual(approval_tool.verify_command(Namespace(
                **expired, approval=[str(path) for path in approvals]
            )), 2)

            original_payload = payload_path.read_bytes()
            payload_path.write_bytes(b"{}\n")
            self.assertEqual(approval_tool.verify_command(Namespace(
                **common, approval=[str(path) for path in approvals]
            )), 2)
            payload_path.write_bytes(original_payload)

            revoked_policy = copy.deepcopy(policy)
            revoked_policy["revokedKeys"] = [{
                "keyId": "approval-key-a", "revokedAt":
                    "2026-08-27T11:00:00+00:00", "reason": "compromised",
            }]
            revoked_path = root / "revoked-policy.json"
            revoked_sha = write_json(revoked_path, revoked_policy)
            revoked_subject_path = root / "revoked-subject.json"
            self.assertEqual(approval_tool.subject_command(Namespace(
                payload=str(payload_path), expected_payload_sha256=payload_sha,
                expected_payload_product="ExampleProductionChange",
                policy=str(revoked_path), expected_policy_id="production-governance",
                expected_policy_sha256=revoked_sha,
                subject_id="change-42-revoked-approval",
                subject_type="production-change-request", role="production-change",
                initiator_id="release-author", reason="revocation test",
                issued_at=NOW, lifetime_seconds=3600,
                output=str(revoked_subject_path),
            )), 0)
            revoked_subject_sha = hashlib.sha256(
                revoked_subject_path.read_bytes()
            ).hexdigest()
            revoked_approvals: list[Path] = []
            for person, key_id in (
                    ("security-a", "approval-key-a"),
                    ("security-b", "approval-key-b")):
                output = root / f"{person}.revoked-approval.json"
                os.environ["PDR_GOVERNANCE_APPROVAL_KEY"] = str(material[key_id][0])
                self.assertEqual(approval_tool.approve_command(Namespace(
                    subject=str(revoked_subject_path),
                    expected_subject_sha256=revoked_subject_sha,
                    approver_id=person, key_id=key_id,
                    private_key_environment="PDR_GOVERNANCE_APPROVAL_KEY",
                    verification_time=NOW, output=str(output),
                )), 0)
                revoked_approvals.append(output)
            revoked_verify = dict(
                subject=str(revoked_subject_path),
                expected_subject_sha256=revoked_subject_sha,
                payload=str(payload_path), expected_payload_sha256=payload_sha,
                policy=str(revoked_path), expected_policy_id="production-governance",
                expected_policy_sha256=revoked_sha,
                approval=[str(path) for path in revoked_approvals],
                trusted_keys_directory=str(keys), executor_id="release-operator",
                verification_time=NOW, report=None,
            )
            self.assertEqual(
                approval_tool.verify_command(Namespace(**revoked_verify)), 2
            )

            original_key = (keys / "approval-key-b.pem").read_bytes()
            (keys / "approval-key-b.pem").write_bytes(b"changed\n")
            self.assertEqual(approval_tool.verify_command(Namespace(
                **common, approval=[str(path) for path in approvals]
            )), 2)
            (keys / "approval-key-b.pem").write_bytes(original_key)

    def test_public_cli_exposes_portable_approval_protocol(self) -> None:
        for operation in ("subject", "approve", "verify"):
            completed = subprocess.run([
                sys.executable, str(ROOT / "tools" / "pdr.py"),
                "contract-package", f"governance-approval-{operation}", "--help",
            ], capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_common_engine_preserves_two_existing_approval_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            keys = root / "keys"
            keys.mkdir()
            private_a, public_a = key_pair(keys, "approval-key-a")
            private_b, public_b = key_pair(keys, "approval-key-b")
            subject = package_tool.json_bytes({
                "schemaVersion": 1, "product": "ExampleLegacyProposal",
                "proposalId": "legacy-proposal",
            })
            subject_sha = package_tool.sha256_bytes(subject)
            allowed = [
                {"approverId": "security-a", "keyId": "approval-key-a",
                 "algorithm": "Ed25519", "publicKeySha256": public_a,
                 "roles": ["standard"]},
                {"approverId": "security-b", "keyId": "approval-key-b",
                 "algorithm": "Ed25519", "publicKeySha256": public_b,
                 "roles": ["standard"]},
            ]
            for product, validator in (
                    (trust_control.APPROVAL_PRODUCT,
                     trust_control.validate_approval),
                    (trust_state.MIGRATION_APPROVAL_PRODUCT,
                     trust_state.validate_migration_approval)):
                loaded = []
                for person, key_id, private in (
                        ("security-a", "approval-key-a", private_a),
                        ("security-b", "approval-key-b", private_b)):
                    os.environ["PDR_GOVERNANCE_APPROVAL_KEY"] = str(private)
                    document = approval_tool.sign_ed25519_document(
                        subject, subject_sha, approver_id=person, key_id=key_id,
                        private_key_environment="PDR_GOVERNANCE_APPROVAL_KEY",
                        product=product, subject_sha_field="proposalSha256",
                    )
                    validator(document)
                    content = package_tool.json_bytes(document)
                    loaded.append((
                        document, root / f"{product}-{person}.json", content,
                        package_tool.sha256_bytes(content),
                    ))
                verified = approval_tool.verify_ed25519_quorum(
                    subject_content=subject, subject_sha256=subject_sha,
                    initiator_id="release-author",
                    executor_id="release-operator", required_role="standard",
                    minimum_approvals=2, allowed_approvers=allowed,
                    allowed_executor_ids=["release-operator"], revoked_keys=[],
                    approvals=loaded, approval_validator=validator,
                    subject_sha_field="proposalSha256",
                    trusted_keys_directory=keys,
                    verification_time=package_tool.verification_time(NOW),
                )
                self.assertEqual(len(verified), 2)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    if result.wasSuccessful():
        print("PDR_GOVERNANCE_APPROVAL_PASS generic=1 payloadPin=1 policyPin=1 "
              "roles=1 quorum=2 separation=1 revocation=1 expiry=1 keyPin=1 "
              "customEnvelope=2 cli=3 redaction=1")
    raise SystemExit(0 if result.wasSuccessful() else 1)
