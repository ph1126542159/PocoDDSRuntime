#!/usr/bin/env python3
"""Creation-time Governance Approval Signer admission tests."""

from __future__ import annotations

import base64
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import team_contract_adapter_certifier_trust_control as trust_control
import team_contract_adapter_certifier_trust_state_store as trust_state
import team_contract_adapter_conformance as conformance_tool
import team_contract_adapter_conformance_trust as conformance_trust
import team_contract_governance_approval as approval_tool
import team_contract_governance_approval_signer as signer_tool
import team_contract_governance_approval_signer_admission as admission_tool
import team_contract_package as package_tool


PURPOSES = sorted(signer_tool.ALLOWED_PURPOSES)


def key_pair(private_path: Path, public_path: Path) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )
    key = Ed25519PrivateKey.generate()
    private_path.write_bytes(key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ))
    public_path.write_bytes(key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    ))


class GovernanceApprovalSignerAdmissionTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        print(
            "PDR_GOVERNANCE_APPROVAL_SIGNER_ADMISSION_PASS config=1 "
            "evidence=1 age=1 attestation=1 trust=1 revocation=1 "
            "currentSigner=1 envelopeV3=3 domainBinding=1 pins=1 "
            "redaction=1 cli=3 compatibility=1"
        )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.now = package_tool.verification_time(None)
        self.signer_private = self.root / "signer.private.pem"
        self.signer_public = self.root / "approval-key-a.pem"
        key_pair(self.signer_private, self.signer_public)
        source = ROOT / \
            "examples/team-contract-governance-approval-signer-local" / \
            "local_ed25519_governance_approval_signer_adapter.py"
        self.adapter = self.root / "signer-adapter.py"
        shutil.copy2(source, self.adapter)
        self.mapping = self.root / "mapping.json"
        package_tool.write_json(self.mapping, {
            "schemaVersion": 1,
            "product":
                "PocoDDSRuntimeTeamContractGovernanceApprovalSignerLocalMapping",
            "signerId": "admitted-approval-kms",
            "approverId": "security-a", "purposes": PURPOSES,
            "keys": [{
                "keyId": "approval-key-a",
                "privateKeyEnvironment": "PDR_TEST_ADMITTED_SIGNER_KEY",
            }],
        })
        self.config = self.root / "signer-config.json"
        package_tool.write_json(self.config, {
            "schemaVersion": 1, "product": signer_tool.CONFIG_PRODUCT,
            "signerId": "admitted-approval-kms",
            "approverId": "security-a", "kind": "external-command",
            "protocolMajor": 1, "minimumProtocolMinor": 0,
            "requiredCapabilities": signer_tool.REQUIRED_CAPABILITIES,
            "purposes": PURPOSES,
            "keys": [{
                "keyId": "approval-key-a", "algorithm": "Ed25519",
                "publicKey": str(self.signer_public),
                "publicKeySha256": package_tool.sha256_file(
                    self.signer_public
                ),
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
                "PDR_TEST_ADMITTED_SIGNER_KEY",
            ],
            "timeoutSeconds": 2, "maxResponseBytes": 16384,
            "maxPayloadBytes": 4096,
        })
        self.config_sha = package_tool.sha256_file(self.config)
        os.environ["PDR_TEST_ADMITTED_SIGNER_KEY"] = str(
            self.signer_private
        )

        self.evidence_path = self.root / "conformance.json"
        self.assertEqual(conformance_tool.execute_command(Namespace(
            adapter_kind="governance-approval-signer",
            config=str(self.config), expected_config_sha256=self.config_sha,
            scope_primary="security-a", scope_secondary=None,
            report=str(self.evidence_path),
        )), 0)
        self.evidence = json.loads(self.evidence_path.read_bytes())

        keys = self.root / "keys"
        keys.mkdir()
        self.certifier_private = self.root / "certifier.private.pem"
        self.certifier_public = keys / "certifier.pem"
        key_pair(self.certifier_private, self.certifier_public)
        os.environ["PDR_TEST_ADMISSION_CERTIFIER_KEY"] = str(
            self.certifier_private
        )
        self.policy_path = self.root / "trust-policy.json"
        self.policy = {
            "schemaVersion": 1, "product": conformance_trust.POLICY_PRODUCT,
            "policyId": "approval-signer-admission", "generation": 4,
            "maximumAttestationLifetimeSeconds": 3600,
            "allowedCertifiers": [{
                "certifierId": "runtime-certifier",
                "keyId": "certifier-key-a", "algorithm": "Ed25519",
                "publicKey": "keys/certifier.pem",
                "publicKeySha256": package_tool.sha256_file(
                    self.certifier_public
                ), "adapterKinds": ["governance-approval-signer"],
                "adapterIds": ["admitted-approval-kms"],
                "notBefore": (self.now - timedelta(hours=1)).isoformat(),
                "notAfter": (self.now + timedelta(days=1)).isoformat(),
            }], "revokedKeys": [],
        }
        package_tool.write_json(self.policy_path, self.policy)
        self.attestation_path = self.root / "attestation.json"
        self.assertEqual(conformance_trust.attest_command(Namespace(
            evidence=str(self.evidence_path),
            expected_evidence_sha256=package_tool.sha256_file(
                self.evidence_path
            ), certifier_id="runtime-certifier", key_id="certifier-key-a",
            private_key_environment="PDR_TEST_ADMISSION_CERTIFIER_KEY",
            private_key_passphrase_environment=None, signer_config=None,
            expected_signer_config_sha256=None,
            issued_at=self.now.isoformat(), lifetime_seconds=1800,
            report=str(self.attestation_path),
        )), 0)
        self.admission_config = self.root / "admission-config.json"
        self.write_admission_config(
            self.admission_config, self.policy_path,
            package_tool.sha256_file(self.policy_path),
        )
        self.admission_config_sha = package_tool.sha256_file(
            self.admission_config
        )

    def tearDown(self) -> None:
        os.environ.pop("PDR_TEST_ADMITTED_SIGNER_KEY", None)
        os.environ.pop("PDR_TEST_ADMISSION_CERTIFIER_KEY", None)
        self.temp.cleanup()

    def write_admission_config(self, path: Path, policy_path: Path,
                               policy_sha: str) -> None:
        package_tool.write_json(path, {
            "schemaVersion": 1, "product": admission_tool.CONFIG_PRODUCT,
            "evidence": str(self.evidence_path),
            "expectedEvidenceSha256": package_tool.sha256_file(
                self.evidence_path
            ), "attestation": str(self.attestation_path),
            "expectedAttestationSha256": package_tool.sha256_file(
                self.attestation_path
            ), "trustPolicy": str(policy_path),
            "expectedTrustPolicyId": "approval-signer-admission",
            "minimumTrustPolicyGeneration": 4,
            "expectedTrustPolicySha256": policy_sha,
            "maximumEvidenceAgeSeconds": 2678400,
        })

    def sign(self, product: str, sha_field: str, purpose: str,
             *, extra: dict | None = None,
             admission_config: Path | None = None,
             admission_sha: str | None = None) -> dict:
        content = b'{"governed":"admitted"}\n'
        return approval_tool.sign_governed_approval(
            content, package_tool.sha256_bytes(content),
            approver_id="security-a", key_id="approval-key-a",
            product=product, subject_sha_field=sha_field, purpose=purpose,
            signer_config=str(self.config),
            expected_signer_config_sha256=self.config_sha,
            signer_admission_config=str(
                admission_config or self.admission_config
            ), expected_signer_admission_config_sha256=
                admission_sha or self.admission_config_sha,
            verification_time=self.now, extra_fields=extra,
        )

    def test_admitted_v3_envelopes_are_domain_bound(self) -> None:
        generic = self.sign(
            approval_tool.APPROVAL_PRODUCT, "subjectSha256",
            "governance-approval", extra={"subjectId": "change-admitted"},
        )
        trust = self.sign(
            trust_control.APPROVAL_PRODUCT, "proposalSha256",
            "adapter-certifier-trust-approval",
        )
        migration = self.sign(
            trust_state.MIGRATION_APPROVAL_PRODUCT, "proposalSha256",
            "adapter-certifier-trust-migration-approval",
        )
        approval_tool.validate_approval(generic)
        trust_control.validate_approval(trust)
        trust_state.validate_migration_approval(migration)
        for envelope in (generic, trust, migration):
            self.assertEqual(envelope["schemaVersion"], 3)
            self.assertEqual(envelope["signerConformanceTrustPolicyGeneration"],
                             4)
            serialized = json.dumps(envelope, sort_keys=True)
            self.assertNotIn(str(self.root), serialized)
            self.assertNotIn("private.pem", serialized)

        content = b'{"governed":"admitted"}\n'
        generic_bytes = package_tool.json_bytes(generic)
        allowed = [{
            "approverId": "security-a", "keyId": "approval-key-a",
            "algorithm": "Ed25519",
            "publicKeySha256": package_tool.sha256_file(self.signer_public),
            "roles": ["standard"],
        }]
        self.assertEqual(len(approval_tool.verify_ed25519_quorum(
            subject_content=content,
            subject_sha256=package_tool.sha256_bytes(content),
            initiator_id="release-author", executor_id="release-operator",
            required_role="standard", minimum_approvals=1,
            allowed_approvers=allowed,
            allowed_executor_ids=["release-operator"], revoked_keys=[],
            approvals=[(generic, self.root / "approval.json", generic_bytes,
                        package_tool.sha256_bytes(generic_bytes))],
            approval_validator=approval_tool.validate_approval,
            subject_sha_field="subjectSha256",
            trusted_keys_directory=self.root, verification_time=self.now,
            external_signer_purpose="governance-approval",
        )), 1)
        tampered = copy.deepcopy(generic)
        tampered["signerConformanceTrustPolicyGeneration"] = 5
        tampered_bytes = package_tool.json_bytes(tampered)
        with self.assertRaisesRegex(ValueError, "signature failed"):
            approval_tool.verify_ed25519_quorum(
                subject_content=content,
                subject_sha256=package_tool.sha256_bytes(content),
                initiator_id="release-author",
                executor_id="release-operator", required_role="standard",
                minimum_approvals=1, allowed_approvers=allowed,
                allowed_executor_ids=["release-operator"], revoked_keys=[],
                approvals=[(tampered, self.root / "tampered.json",
                            tampered_bytes,
                            package_tool.sha256_bytes(tampered_bytes))],
                approval_validator=approval_tool.validate_approval,
                subject_sha_field="subjectSha256",
                trusted_keys_directory=self.root,
                verification_time=self.now,
                external_signer_purpose="governance-approval",
            )

        v2 = approval_tool.sign_governed_approval(
            content, package_tool.sha256_bytes(content),
            approver_id="security-a", key_id="approval-key-a",
            product=approval_tool.APPROVAL_PRODUCT,
            subject_sha_field="subjectSha256", purpose="governance-approval",
            signer_config=str(self.config),
            expected_signer_config_sha256=self.config_sha,
            extra_fields={"subjectId": "change-v2"},
        )
        self.assertEqual(v2["schemaVersion"], 2)

    def test_admission_faults_fail_closed(self) -> None:
        signer = signer_tool.ExternalCommandGovernanceApprovalSigner(
            self.config, self.config_sha
        )
        descriptor = admission_tool.admit(
            self.admission_config, self.admission_config_sha,
            signer=signer, verification_time=self.now,
        )
        self.assertEqual(descriptor["signerConformanceCertifierId"],
                         "runtime-certifier")
        with self.assertRaisesRegex(ValueError, "identity is not pinned"):
            admission_tool.admit(
                self.admission_config, "0" * 64,
                signer=signer, verification_time=self.now,
            )
        with self.assertRaisesRegex(ValueError, "outside age policy"):
            admission_tool.admit(
                self.admission_config, self.admission_config_sha,
                signer=signer,
                verification_time=self.now + timedelta(days=32),
            )

        changed_config = self.root / "changed-signer-config.json"
        changed_document = json.loads(self.config.read_bytes())
        changed_document["timeoutSeconds"] = 3
        package_tool.write_json(changed_config, changed_document)
        changed_signer = signer_tool.ExternalCommandGovernanceApprovalSigner(
            changed_config, package_tool.sha256_file(changed_config)
        )
        with self.assertRaisesRegex(ValueError, "does not match current signer"):
            admission_tool.admit(
                self.admission_config, self.admission_config_sha,
                signer=changed_signer, verification_time=self.now,
            )

        revoked_policy = copy.deepcopy(self.policy)
        revoked_policy["revokedKeys"] = [{
            "keyId": "certifier-key-a", "revokedAt":
                self.now.isoformat(), "reason": "compromised",
        }]
        revoked_path = self.root / "revoked-policy.json"
        package_tool.write_json(revoked_path, revoked_policy)
        revoked_config = self.root / "revoked-admission.json"
        self.write_admission_config(
            revoked_config, revoked_path,
            package_tool.sha256_file(revoked_path),
        )
        with self.assertRaisesRegex(ValueError, "untrusted or revoked"):
            admission_tool.admit(
                revoked_config, package_tool.sha256_file(revoked_config),
                signer=signer, verification_time=self.now,
            )

        with self.assertRaisesRegex(ValueError, "complete external mode"):
            approval_tool.sign_governed_approval(
                b"local", package_tool.sha256_bytes(b"local"),
                approver_id="security-a", key_id="approval-key-a",
                product=approval_tool.APPROVAL_PRODUCT,
                subject_sha_field="subjectSha256",
                purpose="governance-approval",
                private_key_environment="PDR_TEST_ADMITTED_SIGNER_KEY",
                signer_admission_config=str(self.admission_config),
                expected_signer_admission_config_sha256=
                    self.admission_config_sha,
            )

    def test_public_approve_commands_expose_admission(self) -> None:
        for command in (
                "governance-approval-approve",
                "adapter-certifier-trust-approve",
                "adapter-certifier-trust-remote-migration-approve"):
            result = subprocess.run([
                sys.executable, str(TOOLS / "pdr.py"), "contract-package",
                command, "--help",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--signer-admission-config", result.stdout)
            self.assertIn(
                "--expected-signer-admission-config-sha256", result.stdout
            )


if __name__ == "__main__":
    unittest.main()
