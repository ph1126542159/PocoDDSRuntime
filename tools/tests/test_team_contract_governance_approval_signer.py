#!/usr/bin/env python3
"""External Governance Approval Signer protocol and integration tests."""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import team_contract_adapter_certifier_trust_control as trust_control
import team_contract_adapter_certifier_trust_state_store as trust_state
import team_contract_governance_approval as approval_tool
import team_contract_governance_approval_signer as signer_tool
import team_contract_package as package_tool


PURPOSES = sorted(signer_tool.ALLOWED_PURPOSES)


class GovernanceApprovalSignerTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        print(
            "PDR_GOVERNANCE_APPROVAL_SIGNER_PASS protocol=1 capability=1 "
            "external=1 purpose=3 keyRouting=1 payloadPin=1 configPin=1 "
            "artifactPin=1 environment=1 signatureVerify=1 rejection=1 "
            "redaction=1 domainBinding=1 envelopeV2=3 localCompatible=1"
        )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        from cryptography.hazmat.primitives.asymmetric.ed25519 import \
            Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding, NoEncryption, PrivateFormat, PublicFormat,
        )
        private = Ed25519PrivateKey.generate()
        self.private_path = self.root / "private.pem"
        self.public_path = self.root / "approval-key-a.pem"
        self.private_path.write_bytes(private.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        ))
        self.public_path.write_bytes(private.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        ))
        source = ROOT / \
            "examples/team-contract-governance-approval-signer-local" / \
            "local_ed25519_governance_approval_signer_adapter.py"
        self.adapter = self.root / "approval-signer-adapter.py"
        shutil.copy2(source, self.adapter)
        self.mapping = self.root / "mapping.json"
        package_tool.write_json(self.mapping, {
            "schemaVersion": 1,
            "product":
                "PocoDDSRuntimeTeamContractGovernanceApprovalSignerLocalMapping",
            "signerId": "test-approval-kms", "approverId": "security-a",
            "purposes": PURPOSES,
            "keys": [{
                "keyId": "approval-key-a",
                "privateKeyEnvironment": "PDR_TEST_APPROVAL_SIGNER_KEY",
            }],
        })
        self.config = self.root / "config.json"
        package_tool.write_json(self.config, {
            "schemaVersion": 1, "product": signer_tool.CONFIG_PRODUCT,
            "signerId": "test-approval-kms", "approverId": "security-a",
            "kind": "external-command", "protocolMajor": 1,
            "minimumProtocolMinor": 0,
            "requiredCapabilities": signer_tool.REQUIRED_CAPABILITIES,
            "purposes": PURPOSES,
            "keys": [{
                "keyId": "approval-key-a", "algorithm": "Ed25519",
                "publicKey": str(self.public_path),
                "publicKeySha256": package_tool.sha256_file(self.public_path),
            }],
            "executable": str(Path(sys.executable).resolve()),
            "executableSha256": package_tool.sha256_file(
                Path(sys.executable).resolve()
            ),
            "arguments": [str(self.adapter), "--mapping", str(self.mapping)],
            "artifactPins": [
                {"path": str(self.adapter),
                 "sha256": package_tool.sha256_file(self.adapter)},
                {"path": str(self.mapping),
                 "sha256": package_tool.sha256_file(self.mapping)},
            ],
            "environmentVariables": [],
            "optionalEnvironmentVariables": [
                "PDR_APPROVAL_SIGNER_FAULT", "PDR_TEST_APPROVAL_SIGNER_KEY",
            ],
            "timeoutSeconds": 2, "maxResponseBytes": 16384,
            "maxPayloadBytes": 4096,
        })
        self.config_sha = package_tool.sha256_file(self.config)
        os.environ["PDR_TEST_APPROVAL_SIGNER_KEY"] = str(self.private_path)

    def tearDown(self) -> None:
        os.environ.pop("PDR_TEST_APPROVAL_SIGNER_KEY", None)
        os.environ.pop("PDR_APPROVAL_SIGNER_FAULT", None)
        self.temp.cleanup()

    def external(self, *, product: str, sha_field: str, purpose: str,
                 content: bytes = b'{"governed":true}\n',
                 extra_fields: dict | None = None) -> dict:
        return approval_tool.sign_governed_approval(
            content, package_tool.sha256_bytes(content),
            approver_id="security-a", key_id="approval-key-a",
            product=product, subject_sha_field=sha_field, purpose=purpose,
            signer_config=str(self.config),
            expected_signer_config_sha256=self.config_sha,
            extra_fields=extra_fields,
        )

    def test_external_signer_purpose_binding_and_v2_envelopes(self) -> None:
        signer = signer_tool.ExternalCommandGovernanceApprovalSigner(
            self.config, self.config_sha
        )
        for purpose in PURPOSES:
            self.assertEqual(len(signer.sign(b"governed-payload",
                                             "approval-key-a", purpose)), 64)
        descriptor = signer.descriptor()
        self.assertEqual(descriptor["signerId"], "test-approval-kms")
        self.assertNotIn(str(self.root), json.dumps(descriptor))
        self.assertEqual(
            set(signer.capability_manifest["capabilities"]),
            set(signer_tool.REQUIRED_CAPABILITIES),
        )

        generic = self.external(
            product=approval_tool.APPROVAL_PRODUCT,
            sha_field="subjectSha256", purpose="governance-approval",
            extra_fields={"subjectId": "change-42"},
        )
        trust = self.external(
            product=trust_control.APPROVAL_PRODUCT,
            sha_field="proposalSha256",
            purpose="adapter-certifier-trust-approval",
        )
        migration = self.external(
            product=trust_state.MIGRATION_APPROVAL_PRODUCT,
            sha_field="proposalSha256",
            purpose="adapter-certifier-trust-migration-approval",
        )
        approval_tool.validate_approval(generic)
        trust_control.validate_approval(trust)
        trust_state.validate_migration_approval(migration)
        for envelope in (generic, trust, migration):
            self.assertEqual(envelope["schemaVersion"], 2)
            serialized = json.dumps(envelope, sort_keys=True)
            self.assertNotIn(str(self.root), serialized)
            self.assertNotIn("private", serialized.lower())

        generic_content = package_tool.json_bytes(generic)
        allowed = [{
            "approverId": "security-a", "keyId": "approval-key-a",
            "algorithm": "Ed25519",
            "publicKeySha256": package_tool.sha256_file(self.public_path),
            "roles": ["standard"],
        }]
        verified = approval_tool.verify_ed25519_quorum(
            subject_content=b'{"governed":true}\n',
            subject_sha256=package_tool.sha256_bytes(b'{"governed":true}\n'),
            initiator_id="release-author", executor_id="release-operator",
            required_role="standard", minimum_approvals=1,
            allowed_approvers=allowed,
            allowed_executor_ids=["release-operator"], revoked_keys=[],
            approvals=[(generic, self.root / "generic.json", generic_content,
                        package_tool.sha256_bytes(generic_content))],
            approval_validator=approval_tool.validate_approval,
            subject_sha_field="subjectSha256",
            trusted_keys_directory=self.root,
            verification_time=package_tool.verification_time(
                "2026-08-27T12:00:00+00:00"
            ), external_signer_purpose="governance-approval",
        )
        self.assertEqual(len(verified), 1)
        for envelope, validator, purpose in (
                (trust, trust_control.validate_approval,
                 "adapter-certifier-trust-approval"),
                (migration, trust_state.validate_migration_approval,
                 "adapter-certifier-trust-migration-approval")):
            envelope_content = package_tool.json_bytes(envelope)
            self.assertEqual(len(approval_tool.verify_ed25519_quorum(
                subject_content=b'{"governed":true}\n',
                subject_sha256=package_tool.sha256_bytes(
                    b'{"governed":true}\n'
                ), initiator_id="release-author",
                executor_id="release-operator", required_role="standard",
                minimum_approvals=1, allowed_approvers=allowed,
                allowed_executor_ids=["release-operator"], revoked_keys=[],
                approvals=[(envelope, self.root / "approval.json",
                            envelope_content,
                            package_tool.sha256_bytes(envelope_content))],
                approval_validator=validator,
                subject_sha_field="proposalSha256",
                trusted_keys_directory=self.root,
                verification_time=package_tool.verification_time(
                    "2026-08-27T12:00:00+00:00"
                ), external_signer_purpose=purpose,
            )), 1)
        with self.assertRaisesRegex(ValueError, "signature failed"):
            approval_tool.verify_ed25519_quorum(
                subject_content=b'{"governed":true}\n',
                subject_sha256=package_tool.sha256_bytes(
                    b'{"governed":true}\n'
                ), initiator_id="release-author",
                executor_id="release-operator", required_role="standard",
                minimum_approvals=1, allowed_approvers=allowed,
                allowed_executor_ids=["release-operator"], revoked_keys=[],
                approvals=[(generic, self.root / "wrong-purpose.json",
                            generic_content,
                            package_tool.sha256_bytes(generic_content))],
                approval_validator=approval_tool.validate_approval,
                subject_sha_field="subjectSha256",
                trusted_keys_directory=self.root,
                verification_time=package_tool.verification_time(
                    "2026-08-27T12:00:00+00:00"
                ), external_signer_purpose=
                    "adapter-certifier-trust-approval",
            )
        tampered = copy.deepcopy(generic)
        tampered["signerConfigSha256"] = "d" * 64
        tampered_content = package_tool.json_bytes(tampered)
        with self.assertRaisesRegex(ValueError, "signature failed"):
            approval_tool.verify_ed25519_quorum(
                subject_content=b'{"governed":true}\n',
                subject_sha256=package_tool.sha256_bytes(
                    b'{"governed":true}\n'
                ), initiator_id="release-author",
                executor_id="release-operator", required_role="standard",
                minimum_approvals=1, allowed_approvers=allowed,
                allowed_executor_ids=["release-operator"], revoked_keys=[],
                approvals=[(tampered, self.root / "tampered.json",
                            tampered_content,
                            package_tool.sha256_bytes(tampered_content))],
                approval_validator=approval_tool.validate_approval,
                subject_sha_field="subjectSha256",
                trusted_keys_directory=self.root,
                verification_time=package_tool.verification_time(
                    "2026-08-27T12:00:00+00:00"
                ), external_signer_purpose="governance-approval",
            )

        os.environ["PDR_LOCAL_APPROVAL_KEY"] = str(self.private_path)
        try:
            local = approval_tool.sign_governed_approval(
                b"local", package_tool.sha256_bytes(b"local"),
                approver_id="security-a", key_id="approval-key-a",
                product=approval_tool.APPROVAL_PRODUCT,
                subject_sha_field="subjectSha256",
                purpose="governance-approval",
                private_key_environment="PDR_LOCAL_APPROVAL_KEY",
                extra_fields={"subjectId": "local-change"},
            )
            self.assertEqual(local["schemaVersion"], 1)
            approval_tool.validate_approval(local)
        finally:
            os.environ.pop("PDR_LOCAL_APPROVAL_KEY", None)

    def test_generic_approval_command_uses_external_signer(self) -> None:
        subject = {
            "schemaVersion": 1, "product": approval_tool.SUBJECT_PRODUCT,
            "subjectId": "change-42", "subjectType": "release-change",
            "role": "production-change", "payloadProduct": "ExampleChange",
            "payloadSha256": "a" * 64, "policyId": "production-governance",
            "policySha256": "b" * 64, "initiatorId": "release-author",
            "reason": "approve exact release change",
            "issuedAt": "2026-08-27T10:00:00+00:00",
            "expiresAt": "2026-08-27T14:00:00+00:00",
        }
        subject_path = self.root / "subject.json"
        package_tool.write_json(subject_path, subject)
        output = self.root / "approval.json"
        self.assertEqual(approval_tool.approve_command(Namespace(
            subject=str(subject_path),
            expected_subject_sha256=package_tool.sha256_file(subject_path),
            approver_id="security-a", key_id="approval-key-a",
            private_key_environment=None, signer_config=str(self.config),
            expected_signer_config_sha256=self.config_sha,
            verification_time="2026-08-27T12:00:00+00:00",
            output=str(output),
        )), 0)
        document = json.loads(output.read_bytes())
        approval_tool.validate_approval(document)
        self.assertEqual(document["schemaVersion"], 2)

    def test_faults_identity_and_pins_fail_closed(self) -> None:
        signer = signer_tool.ExternalCommandGovernanceApprovalSigner(
            self.config, self.config_sha
        )
        for fault, message in (
                ("corrupt-signature", "verification failed"),
                ("wrong-key-id", "response is malformed"),
                ("wrong-purpose", "response is malformed"),
                ("wrong-approver-id", "response is malformed"),
                ("reject", "rejected request")):
            os.environ["PDR_APPROVAL_SIGNER_FAULT"] = fault
            with self.assertRaisesRegex((ValueError, RuntimeError), message):
                signer.sign(b"governed-payload", "approval-key-a",
                            "adapter-certifier-trust-approval")
        os.environ.pop("PDR_APPROVAL_SIGNER_FAULT", None)
        os.environ["PDR_UNAPPROVED_SECRET"] = "must-not-cross-boundary"
        os.environ["PDR_APPROVAL_SIGNER_FAULT"] = \
            "detect-unapproved-environment"
        try:
            self.assertEqual(len(signer.sign(
                b"governed-payload", "approval-key-a",
                "governance-approval"
            )), 64)
        finally:
            os.environ.pop("PDR_UNAPPROVED_SECRET", None)
            os.environ.pop("PDR_APPROVAL_SIGNER_FAULT", None)
        with self.assertRaisesRegex(ValueError, "identity is not pinned"):
            signer_tool.ExternalCommandGovernanceApprovalSigner(
                self.config, "0" * 64
            )
        with self.assertRaisesRegex(ValueError, "request is malformed"):
            signer.sign(b"governed-payload", "approval-key-a", "unknown")
        with self.assertRaisesRegex(ValueError, "approver identity changed"):
            approval_tool.sign_governed_approval(
                b"governed", package_tool.sha256_bytes(b"governed"),
                approver_id="security-b", key_id="approval-key-a",
                product=approval_tool.APPROVAL_PRODUCT,
                subject_sha_field="subjectSha256",
                purpose="governance-approval",
                signer_config=str(self.config),
                expected_signer_config_sha256=self.config_sha,
            )
        self.adapter.write_text("# drift\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "digest changed"):
            signer.sign(b"governed-payload", "approval-key-a",
                        "governance-approval")


if __name__ == "__main__":
    unittest.main()
