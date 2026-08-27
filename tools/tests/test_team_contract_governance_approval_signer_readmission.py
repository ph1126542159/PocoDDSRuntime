#!/usr/bin/env python3
"""Execution-time Governance Approval Signer readmission tests."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from argparse import Namespace
from datetime import timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
TESTS = TOOLS / "tests"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TESTS))

import team_contract_adapter_certifier_trust_control as trust_control
import team_contract_adapter_certifier_trust_state_store as trust_state
import team_contract_governance_approval as approval_tool
import team_contract_governance_approval_signer_admission as admission_tool
import team_contract_package as package_tool
import test_team_contract_governance_approval_signer_admission as \
    admission_fixture


class GovernanceApprovalSignerReadmissionTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        print(
            "PDR_GOVERNANCE_APPROVAL_SIGNER_READMISSION_PASS mandatory=1 "
            "bundle=1 currentTrust=1 rotation=1 revocation=1 age=1 "
            "coverage=1 provenance=1 evidence=1 redaction=1 "
            "reportBinding=3 cli=3 compatibility=2"
        )

    def setUp(self) -> None:
        self.fixture = admission_fixture.GovernanceApprovalSignerAdmissionTest(
            "test_public_approve_commands_expose_admission"
        )
        self.fixture.setUp()
        self.root = self.fixture.root

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def approval(self, product: str, purpose: str) \
            -> tuple[dict, Path, bytes, str]:
        sha_field = "subjectSha256" if purpose == "governance-approval" \
            else "proposalSha256"
        extra = {"subjectId": "readmission-subject"} \
            if purpose == "governance-approval" else None
        document = self.fixture.sign(
            product, sha_field, purpose, extra=extra
        )
        content = package_tool.json_bytes(document)
        path = self.root / f"{purpose}.approval.json"
        path.write_bytes(content)
        return document, path, content, package_tool.sha256_bytes(content)

    def bundle(self, approvals: list[tuple[dict, Path, bytes, str]],
               config: Path | None = None) -> tuple[Path, str]:
        path = self.root / "readmission-bundle.json"
        config_path = config or self.fixture.admission_config
        package_tool.write_json(path, {
            "schemaVersion": 1,
            "product": admission_tool.READMISSION_BUNDLE_PRODUCT,
            "entries": [{
                "approvalSha256": item[3],
                "admissionConfig": str(config_path),
                "expectedAdmissionConfigSha256":
                    package_tool.sha256_file(config_path),
            } for item in approvals if item[0]["schemaVersion"] == 3],
        })
        return path, package_tool.sha256_file(path)

    def rotated_config(self, generation: int, *, revoke: bool = False,
                       maximum_age: int = 2678400,
                       attestation_lifetime: int = 3600) -> Path:
        policy = copy.deepcopy(self.fixture.policy)
        policy["generation"] = generation
        policy["maximumAttestationLifetimeSeconds"] = attestation_lifetime
        if revoke:
            policy["revokedKeys"] = [{
                "keyId": "certifier-key-a",
                "revokedAt": self.fixture.now.isoformat(),
                "reason": "execution-time incident revocation",
            }]
        policy_path = self.root / f"trust-policy-{generation}.json"
        package_tool.write_json(policy_path, policy)
        config = json.loads(self.fixture.admission_config.read_bytes())
        config.update({
            "trustPolicy": str(policy_path),
            "expectedTrustPolicySha256": package_tool.sha256_file(policy_path),
            "minimumTrustPolicyGeneration": generation,
            "maximumEvidenceAgeSeconds": maximum_age,
        })
        config_path = self.root / f"admission-config-{generation}.json"
        package_tool.write_json(config_path, config)
        return config_path

    def test_current_policy_rotation_and_path_free_evidence(self) -> None:
        approval = self.approval(
            approval_tool.APPROVAL_PRODUCT, "governance-approval"
        )
        bundle, bundle_sha = self.bundle([approval])
        initial = admission_tool.readmit_approvals(
            [approval], bundle_path=bundle,
            expected_bundle_sha256=bundle_sha,
            purpose="governance-approval",
            subject_sha256=package_tool.sha256_bytes(
                b'{"governed":"admitted"}\n'
            ), executor_id="release-operator",
            verification_time=self.fixture.now,
        )
        self.assertEqual(
            initial["approvals"][0]["executionTrustPolicyGeneration"], 4
        )

        for rejected in (
                self.rotated_config(3),
                self.rotated_config(4, attestation_lifetime=3599)):
            rejected_bundle, rejected_sha = self.bundle([approval], rejected)
            with self.assertRaisesRegex(ValueError, "rolled back"):
                admission_tool.readmit_approvals(
                    [approval], bundle_path=rejected_bundle,
                    expected_bundle_sha256=rejected_sha,
                    purpose="governance-approval",
                    subject_sha256=package_tool.sha256_bytes(
                        b'{"governed":"admitted"}\n'
                    ), executor_id="release-operator",
                    verification_time=self.fixture.now,
                )

        rotated = self.rotated_config(5)
        bundle, bundle_sha = self.bundle([approval], rotated)
        report = self.root / "readmission-evidence.json"
        enforced = admission_tool.enforce_readmission(
            [approval], bundle_path=str(bundle),
            expected_bundle_sha256=bundle_sha, report_path=str(report),
            purpose="governance-approval",
            subject_sha256=package_tool.sha256_bytes(
                b'{"governed":"admitted"}\n'
            ), executor_id="release-operator",
            verification_time=self.fixture.now + timedelta(minutes=1),
        )
        assert enforced is not None
        entry = enforced[0]["approvals"][0]
        self.assertEqual(entry["creationTrustPolicyGeneration"], 4)
        self.assertEqual(entry["executionTrustPolicyGeneration"], 5)
        self.assertEqual(enforced[1], package_tool.sha256_file(report))
        serialized = json.dumps(enforced[0], sort_keys=True)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("private", serialized.lower())

    def test_mandatory_coverage_revocation_age_and_compatibility(self) -> None:
        approval = self.approval(
            approval_tool.APPROVAL_PRODUCT, "governance-approval"
        )
        with self.assertRaisesRegex(ValueError, "requires complete"):
            admission_tool.enforce_readmission(
                [approval], bundle_path=None, expected_bundle_sha256=None,
                report_path=None, purpose="governance-approval",
                subject_sha256="0" * 64, executor_id="release-operator",
                verification_time=self.fixture.now,
            )

        bundle, _ = self.bundle([approval])
        malformed = json.loads(bundle.read_bytes())
        malformed["entries"][0]["approvalSha256"] = "f" * 64
        package_tool.write_json(bundle, malformed)
        with self.assertRaisesRegex(ValueError, "coverage"):
            admission_tool.readmit_approvals(
                [approval], bundle_path=bundle,
                expected_bundle_sha256=package_tool.sha256_file(bundle),
                purpose="governance-approval", subject_sha256="0" * 64,
                executor_id="release-operator",
                verification_time=self.fixture.now,
            )

        revoked = self.rotated_config(6, revoke=True)
        bundle, bundle_sha = self.bundle([approval], revoked)
        with self.assertRaisesRegex(ValueError, "revoked"):
            admission_tool.readmit_approvals(
                [approval], bundle_path=bundle,
                expected_bundle_sha256=bundle_sha,
                purpose="governance-approval", subject_sha256="0" * 64,
                executor_id="release-operator",
                verification_time=self.fixture.now,
            )

        stale = self.rotated_config(7, maximum_age=60)
        bundle, bundle_sha = self.bundle([approval], stale)
        with self.assertRaisesRegex(ValueError, "age policy"):
            admission_tool.readmit_approvals(
                [approval], bundle_path=bundle,
                expected_bundle_sha256=bundle_sha,
                purpose="governance-approval", subject_sha256="0" * 64,
                executor_id="release-operator",
                verification_time=self.fixture.now + timedelta(minutes=2),
            )

        content = b'{"governed":"admitted"}\n'
        v2 = approval_tool.sign_governed_approval(
            content, package_tool.sha256_bytes(content),
            approver_id="security-a", key_id="approval-key-a",
            product=approval_tool.APPROVAL_PRODUCT,
            subject_sha_field="subjectSha256", purpose="governance-approval",
            signer_config=str(self.fixture.config),
            expected_signer_config_sha256=self.fixture.config_sha,
            extra_fields={"subjectId": "compatible-v2"},
        )
        v2_content = package_tool.json_bytes(v2)
        loaded_v2 = (v2, self.root / "v2.json", v2_content,
                     package_tool.sha256_bytes(v2_content))
        self.assertIsNone(admission_tool.enforce_readmission(
            [loaded_v2], bundle_path=None, expected_bundle_sha256=None,
            report_path=None, purpose="governance-approval",
            subject_sha256="0" * 64, executor_id="release-operator",
            verification_time=self.fixture.now,
        ))
        with self.assertRaisesRegex(ValueError, "requires schema v3"):
            admission_tool.enforce_readmission(
                [loaded_v2], bundle_path=str(bundle),
                expected_bundle_sha256=bundle_sha,
                report_path=str(self.root / "unused.json"),
                purpose="governance-approval", subject_sha256="0" * 64,
                executor_id="release-operator",
                verification_time=self.fixture.now,
            )

    def test_three_execution_paths_bind_readmission_reports(self) -> None:
        cases = (
            (approval_tool.APPROVAL_PRODUCT, "governance-approval"),
            (trust_control.APPROVAL_PRODUCT,
             "adapter-certifier-trust-approval"),
            (trust_state.MIGRATION_APPROVAL_PRODUCT,
             "adapter-certifier-trust-migration-approval"),
        )
        governance = {
            "standardMinimumApprovals": 1,
            "emergencyMinimumApprovals": 1,
            "allowedApprovers": [{
                "approverId": "security-a", "keyId": "approval-key-a",
                "algorithm": "Ed25519",
                "publicKeySha256": package_tool.sha256_file(
                    self.fixture.signer_public
                ), "roles": ["standard", "emergency-revocation"],
            }], "activatorIds": ["release-operator"], "revokedKeys": [],
        }
        for index, (product, purpose) in enumerate(cases):
            if index == 0:
                payload_path = self.root / "payload.json"
                package_tool.write_json(payload_path, {
                    "schemaVersion": 1, "product": "ReadmissionChange",
                    "changeId": "readmission-change",
                })
                policy_path = self.root / "governance-policy.json"
                package_tool.write_json(policy_path, {
                    "schemaVersion": 1,
                    "product": approval_tool.POLICY_PRODUCT,
                    "policyId": "readmission-governance",
                    "roles": [{
                        "roleId": "standard", "minimumApprovals": 1,
                        "maxSubjectLifetimeSeconds": 1800,
                    }],
                    "allowedApprovers": [{
                        **governance["allowedApprovers"][0],
                        "roles": ["standard"],
                    }],
                    "executorIds": governance["activatorIds"],
                    "revokedKeys": [],
                })
                subject_path = self.root / "subject.json"
                self.assertEqual(approval_tool.subject_command(Namespace(
                    payload=str(payload_path),
                    expected_payload_sha256=package_tool.sha256_file(
                        payload_path
                    ), expected_payload_product="ReadmissionChange",
                    policy=str(policy_path),
                    expected_policy_id="readmission-governance",
                    expected_policy_sha256=package_tool.sha256_file(policy_path),
                    subject_id="readmission-subject",
                    subject_type="readmission-change", role="standard",
                    initiator_id="release-author", reason="execute safely",
                    issued_at=self.fixture.now.isoformat(),
                    lifetime_seconds=1800, output=str(subject_path),
                )), 0)
                subject_content = subject_path.read_bytes()
                document = approval_tool.sign_governed_approval(
                    subject_content,
                    package_tool.sha256_bytes(subject_content),
                    approver_id="security-a", key_id="approval-key-a",
                    product=product, subject_sha_field="subjectSha256",
                    purpose=purpose, signer_config=str(self.fixture.config),
                    expected_signer_config_sha256=self.fixture.config_sha,
                    signer_admission_config=str(
                        self.fixture.admission_config
                    ), expected_signer_admission_config_sha256=
                        self.fixture.admission_config_sha,
                    verification_time=self.fixture.now,
                    extra_fields={"subjectId": "readmission-subject"},
                )
                approval_path = self.root / "governance-approval.json"
                approval_content = package_tool.json_bytes(document)
                approval_path.write_bytes(approval_content)
                approval = (
                    document, approval_path, approval_content,
                    package_tool.sha256_bytes(approval_content),
                )
            else:
                approval = self.approval(product, purpose)
            bundle, bundle_sha = self.bundle([approval])
            args = Namespace(
                signer_readmission_bundle=str(bundle),
                expected_signer_readmission_bundle_sha256=bundle_sha,
                signer_readmission_report=str(
                    self.root / f"readmission-{index}.json"
                ),
            )
            if index == 0:
                evidence_path = self.root / "governance-evidence.json"
                self.assertEqual(approval_tool.verify_command(Namespace(
                    subject=str(subject_path),
                    expected_subject_sha256=package_tool.sha256_file(
                        subject_path
                    ), payload=str(payload_path),
                    expected_payload_sha256=package_tool.sha256_file(
                        payload_path
                    ), policy=str(policy_path),
                    expected_policy_id="readmission-governance",
                    expected_policy_sha256=package_tool.sha256_file(policy_path),
                    approval=[str(approval[1])],
                    trusted_keys_directory=str(self.root),
                    executor_id="release-operator",
                    verification_time=self.fixture.now.isoformat(),
                    signer_readmission_bundle=str(bundle),
                    expected_signer_readmission_bundle_sha256=bundle_sha,
                    signer_readmission_report=args.signer_readmission_report,
                    report=str(evidence_path),
                )), 0)
                evidence = json.loads(evidence_path.read_bytes())
                self.assertEqual(evidence["schemaVersion"], 2)
                self.assertEqual(
                    evidence["signerReadmissionEvidenceSha256"],
                    package_tool.sha256_file(Path(
                        args.signer_readmission_report
                    )),
                )
                verified = evidence["approvals"]
                readmission = (
                    json.loads(Path(args.signer_readmission_report).read_bytes()),
                    evidence["signerReadmissionEvidenceSha256"],
                )
            elif index == 1:
                proposal = ({"mode": "standard", "proposerId": "author"},
                            self.root / "proposal.json",
                            b'{"governed":"admitted"}\n',
                            package_tool.sha256_bytes(
                                b'{"governed":"admitted"}\n'))
                verified, readmission = trust_control._verify_approvals(
                    proposal, governance, self.root, [str(approval[1])],
                    self.fixture.now, "release-operator", args,
                )
            else:
                proposal = ({"proposerId": "author"},
                            self.root / "migration-proposal.json",
                            b'{"governed":"admitted"}\n',
                            package_tool.sha256_bytes(
                                b'{"governed":"admitted"}\n'))
                verified, readmission = trust_state._verify_migration_approvals(
                    proposal, governance, self.root, [str(approval[1])],
                    self.fixture.now, "release-operator", args,
                )
            self.assertEqual(len(verified), 1)
            self.assertIsNotNone(readmission)
            self.assertTrue(Path(args.signer_readmission_report).is_file())

        for command in (
                "governance-approval-verify",
                "adapter-certifier-trust-activate",
                "adapter-certifier-trust-remote-migration-activate"):
            result = subprocess.run([
                sys.executable, str(TOOLS / "pdr.py"), "contract-package",
                command, "--help",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--signer-readmission-bundle", result.stdout)
            self.assertIn(
                "--expected-signer-readmission-bundle-sha256", result.stdout
            )
            self.assertIn("--signer-readmission-report", result.stdout)


if __name__ == "__main__":
    unittest.main()
