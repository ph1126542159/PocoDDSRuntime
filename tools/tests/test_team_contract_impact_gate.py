#!/usr/bin/env python3

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
TOOL = TOOLS / "team_contract_impact_gate.py"
sys.path.insert(0, str(TOOLS))
import team_contract_impact as impact_tool  # noqa: E402


class TeamContractImpactGateTests(unittest.TestCase):
    @staticmethod
    def run_tool(*arguments: str,
                 environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    @staticmethod
    def write_report(root: Path) -> Path:
        identity = {
            "currentLockSha256": "a" * 64,
            "candidateLockSha256": "b" * 64,
            "consumerCatalogSha256": "c" * 64,
        }
        report = {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractUpgradeImpact",
            "operation": "team-contract-upgrade-impact",
            "compatible": True,
            "reviewRequired": True,
            "inputSetSha256": impact_tool.canonical_sha(identity),
            **identity,
            "currentTrustPolicy": None,
            "candidateTrustPolicy": None,
            "trustPolicyChanged": False,
            "breakingChangeCount": 0,
            "attentionChangeCount": 0,
            "affectedConsumerCount": 1,
            "requiredTestLabels": ["component", "service"],
            "ctestLabelRegex": "^(component|service)$",
            "packages": [{
                "packageId": "team.scheduler",
                "status": "changed",
                "severity": "compatible",
                "currentVersion": "1.0.0",
                "candidateVersion": "1.1.0",
                "currentPackageSha256": "d" * 64,
                "candidatePackageSha256": "e" * 64,
                "changedRoles": ["service-contract"],
                "changes": [{
                    "code": "provider-version-upgraded",
                    "severity": "compatible",
                    "role": "service-contract",
                    "subject": "pdr.scheduling",
                    "detail": "Provider version increased",
                }],
            }],
            "affectedConsumers": [{
                "id": "team.workflow",
                "owner": "team.workflow",
                "severity": "attention",
                "requiredTestLabels": ["component", "service"],
                "reasons": [{
                    "packageId": "team.scheduler",
                    "roles": ["service-contract"],
                    "severity": "attention",
                }],
            }],
        }
        impact_tool.validate_report(report)
        path = root / "impact.json"
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def fake_ctest(root: Path, labels: list[str] | None = None,
                   fail: bool = False) -> Path:
        labels = labels or ["component", "service"]
        script = root / "fake_ctest.py"
        script.write_text(
            "import json, pathlib, sys\n"
            f"labels = {labels!r}\n"
            "if '--show-only=json-v1' in sys.argv:\n"
            "  print(json.dumps({'tests':[{'name':'consumer-contract-pass',"
            "'command':['contract-test'], 'properties':["
            "{'name':'LABELS','value':labels},"
            "{'name':'WORKING_DIRECTORY','value':str(pathlib.Path.cwd())}]}]}))\n"
            "  raise SystemExit(0)\n"
            "junit = pathlib.Path(sys.argv[sys.argv.index('--output-junit') + 1])\n"
            "junit.parent.mkdir(parents=True, exist_ok=True)\n"
            + ("junit.write_text('<testsuite tests=\"1\" failures=\"1\" disabled=\"0\" skipped=\"0\"><testcase name=\"consumer-contract-pass\" status=\"run\"><failure/></testcase></testsuite>')\nraise SystemExit(1)\n"
               if fail else
               "junit.write_text('<testsuite tests=\"1\" failures=\"0\" disabled=\"0\" skipped=\"0\"><testcase name=\"consumer-contract-pass\" status=\"run\"/></testsuite>')\nraise SystemExit(0)\n"),
            encoding="utf-8",
        )
        if os.name == "nt":
            wrapper = root / "fake-ctest.cmd"
            wrapper.write_text(
                f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
            )
        else:
            wrapper = root / "fake-ctest"
            wrapper.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
            )
            wrapper.chmod(0o755)
        return wrapper

    @staticmethod
    def approval_fixture(root: Path, revoked: bool = False) -> tuple[Path, Path, str]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        approval = root / "approval"
        keys = approval / "keys"
        keys.mkdir(parents=True)
        private = approval / "workflow.private.pem"
        public = keys / "workflow-owner.pem"
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
        private.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        public.write_bytes(key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        policy = approval / "policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractImpactApprovalPolicy",
            "policyId": "product-impact-owners",
            "maxApprovalLifetimeSeconds": 7200,
            "allowedApprovers": [{
                "owner": "team.workflow",
                "approverId": "workflow-owner",
                "keyId": "workflow-owner-2026",
                "algorithm": "Ed25519",
                "publicKey": "keys/workflow-owner.pem",
                "publicKeySha256": hashlib.sha256(public.read_bytes()).hexdigest(),
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": ([{
                "keyId": "workflow-owner-2026",
                "revokedAt": "2026-08-01T00:00:00Z",
                "reason": "unit test revocation",
            }] if revoked else []),
        }, indent=2) + "\n", encoding="utf-8")
        return private, policy, hashlib.sha256(policy.read_bytes()).hexdigest()

    def execute(self, root: Path, report: Path, ctest: Path,
                name: str = "execution") -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        evidence = root / f"{name}.json"
        junit = root / f"{name}.xml"
        result = self.run_tool(
            "execute", "--report", str(report), "--ctest", str(ctest),
            "--test-dir", str(root), "--config", "Release",
            "--evidence", str(evidence), "--junit", str(junit),
        )
        return result, evidence, junit

    def approve(self, root: Path, report: Path, private: Path,
                name: str = "approval") -> tuple[subprocess.CompletedProcess[str], Path]:
        output = root / f"{name}.json"
        environment_name = "PDR_TEST_IMPACT_APPROVAL_KEY"
        environment = dict(os.environ, **{environment_name: str(private)})
        result = self.run_tool(
            "approve", "--report", str(report), "--owner", "team.workflow",
            "--approver-id", "workflow-owner", "--key-id", "workflow-owner-2026",
            "--private-key-environment", environment_name,
            "--issued-at", "2026-08-25T12:00:00Z", "--lifetime-seconds", "3600",
            "--output", str(output), environment=environment,
        )
        return result, output

    def gate(self, root: Path, report: Path, evidence: Path, junit: Path,
             ctest: Path, policy: Path, policy_sha: str,
             approval: Path | None) -> subprocess.CompletedProcess[str]:
        command = [
            "gate", "--report", str(report), "--evidence", str(evidence),
            "--junit", str(junit), "--ctest", str(ctest), "--test-dir", str(root),
            "--config", "Release", "--approval-policy", str(policy),
            "--expected-approval-policy-id", "product-impact-owners",
            "--expected-approval-policy-sha256", policy_sha,
            "--verification-time", "2026-08-25T12:30:00Z",
            "--gate-report", str(root / "gate.json"),
        ]
        if approval is not None:
            command.extend(["--approval", str(approval)])
        return self.run_tool(*command)

    def test_execute_approve_and_gate_bind_real_catalog_junit_and_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.write_report(root)
            ctest = self.fake_ctest(root)
            execution, evidence, junit = self.execute(root, report, ctest)
            self.assertEqual(execution.returncode, 0, execution.stdout + execution.stderr)
            private, policy, policy_sha = self.approval_fixture(root)
            approval_result, approval = self.approve(root, report, private)
            self.assertEqual(
                approval_result.returncode, 0, approval_result.stdout + approval_result.stderr
            )
            gate = self.gate(
                root, report, evidence, junit, ctest, policy, policy_sha, approval
            )
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            result = json.loads((root / "gate.json").read_text(encoding="utf-8"))
            self.assertTrue(result["passed"])
            self.assertEqual(result["requiredOwners"], ["team.workflow"])
            self.assertEqual(result["approvedOwners"], ["team.workflow"])

    def test_missing_owner_approval_and_revoked_key_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.write_report(root)
            ctest = self.fake_ctest(root)
            execution, evidence, junit = self.execute(root, report, ctest)
            self.assertEqual(execution.returncode, 0)
            private, policy, policy_sha = self.approval_fixture(root)
            missing = self.gate(root, report, evidence, junit, ctest, policy, policy_sha, None)
            self.assertEqual(missing.returncode, 2)
            approval_result, approval = self.approve(root, report, private)
            self.assertEqual(approval_result.returncode, 0)
            _, revoked_policy, revoked_sha = self.approval_fixture(root / "revoked", True)
            revoked = self.gate(
                root, report, evidence, junit, ctest, revoked_policy, revoked_sha, approval
            )
            self.assertEqual(revoked.returncode, 2)
            self.assertIn("revoked", revoked.stderr)

    def test_missing_test_label_and_failed_test_cannot_create_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.write_report(root)
            missing_labels, evidence, _ = self.execute(
                root, report, self.fake_ctest(root, ["component"]), "missing-label"
            )
            self.assertEqual(missing_labels.returncode, 2)
            self.assertFalse(evidence.exists())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.write_report(root)
            failed, evidence, _ = self.execute(
                root, report, self.fake_ctest(root, fail=True), "failed"
            )
            self.assertEqual(failed.returncode, 2)
            self.assertFalse(evidence.exists())

    def test_tampered_junit_and_changed_ctest_catalog_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.write_report(root)
            ctest = self.fake_ctest(root)
            execution, evidence, junit = self.execute(root, report, ctest)
            self.assertEqual(execution.returncode, 0)
            private, policy, policy_sha = self.approval_fixture(root)
            _, approval = self.approve(root, report, private)
            original_junit = junit.read_bytes()
            junit.write_bytes(original_junit + b"\n")
            tampered = self.gate(
                root, report, evidence, junit, ctest, policy, policy_sha, approval
            )
            self.assertEqual(tampered.returncode, 2)
            junit.write_bytes(original_junit)
            relocated_junit = root / "relocated.xml"
            relocated_junit.write_bytes(original_junit)
            relocated = self.gate(
                root, report, evidence, relocated_junit, ctest,
                policy, policy_sha, approval
            )
            self.assertEqual(relocated.returncode, 2)
            self.assertIn("command changed", relocated.stderr)
            fake_script = root / "fake_ctest.py"
            fake_script.write_text(
                fake_script.read_text(encoding="utf-8").replace(
                    "'command':['contract-test']", "'command':['changed-contract-test']"
                ),
                encoding="utf-8",
            )
            changed_catalog = self.gate(
                root, report, evidence, junit, ctest, policy, policy_sha, approval
            )
            self.assertEqual(changed_catalog.returncode, 2)
            self.assertIn("catalog changed", changed_catalog.stderr)


if __name__ == "__main__":
    unittest.main()
