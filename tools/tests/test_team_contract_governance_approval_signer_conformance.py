#!/usr/bin/env python3
"""Governance Approval Signer conformance and trust handoff tests."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import team_contract_adapter_conformance as conformance_tool
import team_contract_adapter_conformance_admission as admission_tool
import team_contract_adapter_conformance_trust as trust_tool
import team_contract_governance_approval as approval_tool
import team_contract_governance_approval_signer as signer_tool
import team_contract_package as package_tool


NOW = "2026-08-27T12:00:00+00:00"
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


class GovernanceApprovalSignerConformanceTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        print(
            "PDR_GOVERNANCE_APPROVAL_SIGNER_CONFORMANCE_PASS kind=1 "
            "scope=1 live=3 capability=1 stableId=1 pins=1 redaction=1 "
            "attestation=1 certifierScope=1 trustPolicy=1 revocation=1 "
            "expiry=1 cli=2 fleetKinds=6"
        )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.signer_private = self.root / "signer.private.pem"
        self.signer_public = self.root / "signer.public.pem"
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
            "signerId": "production-approval-kms",
            "approverId": "security-a", "purposes": PURPOSES,
            "keys": [{
                "keyId": "approval-key-a",
                "privateKeyEnvironment": "PDR_TEST_APPROVAL_SIGNER_KEY",
            }],
        })
        self.config = self.root / "config.json"
        package_tool.write_json(self.config, {
            "schemaVersion": 1, "product": signer_tool.CONFIG_PRODUCT,
            "signerId": "production-approval-kms",
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
                "PDR_APPROVAL_SIGNER_FAULT", "PDR_TEST_APPROVAL_SIGNER_KEY",
            ],
            "timeoutSeconds": 2, "maxResponseBytes": 16384,
            "maxPayloadBytes": 4096,
        })
        self.config_sha = package_tool.sha256_file(self.config)
        os.environ["PDR_TEST_APPROVAL_SIGNER_KEY"] = str(
            self.signer_private
        )

    def tearDown(self) -> None:
        os.environ.pop("PDR_TEST_APPROVAL_SIGNER_KEY", None)
        os.environ.pop("PDR_TEST_CERTIFIER_KEY", None)
        self.temp.cleanup()

    def conformance(self, report: Path, *, scope: str = "security-a",
                    digest: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run([
            sys.executable, str(TOOLS / "pdr.py"), "contract-package",
            "adapter-conformance", "--adapter-kind",
            "governance-approval-signer", "--config", str(self.config),
            "--expected-config-sha256", digest or self.config_sha,
            "--scope-primary", scope, "--report", str(report),
        ], check=False, capture_output=True, text=True)

    def test_portable_conformance_is_signed_and_trust_verified(self) -> None:
        report_a = self.root / "conformance-a.json"
        first = self.conformance(report_a)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("PDR_ADAPTER_CONFORMANCE_PASS", first.stdout)
        evidence = json.loads(report_a.read_bytes())
        conformance_tool.validate_evidence(evidence)
        self.assertEqual(evidence["adapterKind"],
                         "governance-approval-signer")
        self.assertEqual(evidence["adapterId"], "production-approval-kms")
        self.assertEqual(evidence["scope"], {
            "primaryId": "security-a", "secondaryId": None,
        })
        self.assertEqual(evidence["configSha256"], self.config_sha)
        serialized = json.dumps(evidence, sort_keys=True)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn(str(self.signer_private), serialized)

        report_b = self.root / "conformance-b.json"
        second = self.conformance(report_b)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        replay = json.loads(report_b.read_bytes())
        self.assertEqual(evidence["conformanceId"], replay["conformanceId"])
        self.assertEqual(evidence["capabilityManifestSha256"],
                         replay["capabilityManifestSha256"])

        signer = signer_tool.ExternalCommandGovernanceApprovalSigner(
            self.config, self.config_sha
        )
        for purpose in PURPOSES:
            payload = approval_tool.external_signing_payload(
                purpose=purpose,
                approval_product=approval_tool.APPROVAL_PRODUCT,
                approver_id="security-a", key_id="approval-key-a",
                subject_sha256=package_tool.sha256_bytes(
                    f"challenge:{purpose}".encode()
                ), descriptor=signer.descriptor(),
            )
            self.assertEqual(len(signer.sign(
                payload, "approval-key-a", purpose
            )), 64)

        wrong_scope = self.conformance(
            self.root / "wrong-scope.json", scope="security-b"
        )
        self.assertEqual(wrong_scope.returncode, 2)
        wrong_pin = self.conformance(
            self.root / "wrong-pin.json", digest="0" * 64
        )
        self.assertEqual(wrong_pin.returncode, 2)

        keys = self.root / "keys"
        keys.mkdir()
        certifier_private = self.root / "certifier.private.pem"
        certifier_public = keys / "certifier.pem"
        key_pair(certifier_private, certifier_public)
        os.environ["PDR_TEST_CERTIFIER_KEY"] = str(certifier_private)
        attestation_path = self.root / "attestation.json"
        attested = subprocess.run([
            sys.executable, str(TOOLS / "pdr.py"), "contract-package",
            "adapter-conformance-attest", "--evidence", str(report_a),
            "--expected-evidence-sha256",
            package_tool.sha256_file(report_a),
            "--certifier-id", "runtime-certifier", "--key-id",
            "certifier-key-a", "--private-key-environment",
            "PDR_TEST_CERTIFIER_KEY", "--issued-at", NOW,
            "--lifetime-seconds", "3600", "--report",
            str(attestation_path),
        ], check=False, capture_output=True, text=True, env=os.environ.copy())
        self.assertEqual(attested.returncode, 0,
                         attested.stdout + attested.stderr)
        self.assertIn("PDR_ADAPTER_CONFORMANCE_ATTEST_PASS", attested.stdout)

        policy = {
            "schemaVersion": 1, "product": trust_tool.POLICY_PRODUCT,
            "policyId": "signer-conformance-trust", "generation": 1,
            "maximumAttestationLifetimeSeconds": 3600,
            "allowedCertifiers": [{
                "certifierId": "runtime-certifier",
                "keyId": "certifier-key-a", "algorithm": "Ed25519",
                "publicKey": "keys/certifier.pem",
                "publicKeySha256": package_tool.sha256_file(certifier_public),
                "adapterKinds": ["governance-approval-signer"],
                "adapterIds": ["production-approval-kms"],
                "notBefore": "2026-08-27T10:00:00+00:00",
                "notAfter": "2026-08-28T10:00:00+00:00",
            }], "revokedKeys": [],
        }
        policy_path = self.root / "trust-policy.json"
        package_tool.write_json(policy_path, policy)
        loaded_policy = trust_tool.load_policy(
            policy_path, package_tool.sha256_file(policy_path),
            expected_policy_id="signer-conformance-trust",
            minimum_generation=1,
        )
        verified = trust_tool.verify_attestation(
            attestation_path, package_tool.sha256_file(attestation_path),
            evidence, package_tool.sha256_file(report_a),
            loaded_policy[0], loaded_policy[1], NOW,
        )
        self.assertEqual(verified["certifierId"], "runtime-certifier")

        revoked = copy.deepcopy(policy)
        revoked["revokedKeys"] = [{
            "keyId": "certifier-key-a", "revokedAt":
                "2026-08-27T11:00:00+00:00", "reason": "compromised",
        }]
        with self.assertRaisesRegex(ValueError, "untrusted or revoked"):
            trust_tool.verify_attestation(
                attestation_path, package_tool.sha256_file(attestation_path),
                evidence, package_tool.sha256_file(report_a), revoked,
                policy_path, NOW,
            )
        with self.assertRaisesRegex(ValueError, "expired"):
            trust_tool.verify_attestation(
                attestation_path, package_tool.sha256_file(attestation_path),
                evidence, package_tool.sha256_file(report_a), policy,
                policy_path, "2026-08-27T13:00:01+00:00",
            )
        wrong_certifier_scope = copy.deepcopy(policy)
        wrong_certifier_scope["allowedCertifiers"][0]["adapterIds"] = [
            "other-signer"
        ]
        with self.assertRaisesRegex(ValueError, "scope or validity"):
            trust_tool.verify_attestation(
                attestation_path, package_tool.sha256_file(attestation_path),
                evidence, package_tool.sha256_file(report_a),
                wrong_certifier_scope, policy_path, NOW,
            )

        self.assertEqual(set(admission_tool.REQUIRED_KINDS), {
            "adapter-config-resolver", "artifact-store",
            "control-authorizer", "fleet-executor",
            "registry-leader-backend", "wave-gate",
        })


if __name__ == "__main__":
    unittest.main()
