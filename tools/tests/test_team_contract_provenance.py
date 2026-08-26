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
TESTS = Path(__file__).resolve().parent
PROVENANCE_TOOL = TOOLS / "team_contract_provenance.py"
GATE_TOOL = TOOLS / "team_contract_impact_gate.py"
sys.path.insert(0, str(TESTS))
import test_team_contract_impact_gate as impact_test  # noqa: E402
import test_team_contract_registry as registry_test  # noqa: E402


class TeamContractProvenanceTests(unittest.TestCase):
    @staticmethod
    def run_tool(*arguments: str,
                 environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PROVENANCE_TOOL), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    @staticmethod
    def key_pair(root: Path, name: str, seed: bytes) -> tuple[Path, Path]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private = root / f"{name}.private.pem"
        public = root / "keys" / f"{name}.pem"
        public.parent.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.from_private_bytes(seed)
        private.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        public.write_bytes(key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        return private, public

    def execution_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        report = impact_test.TeamContractImpactGateTests.write_report(root)
        ctest = impact_test.TeamContractImpactGateTests.fake_ctest(root)
        evidence = root / "execution.json"
        junit = root / "execution.xml"
        result = subprocess.run([
            sys.executable, str(GATE_TOOL), "execute", "--report", str(report),
            "--ctest", str(ctest), "--test-dir", str(root), "--config", "Release",
            "--evidence", str(evidence), "--junit", str(junit),
        ], check=False, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return report, evidence, junit

    def runner_fixture(self, root: Path, revoked: bool = False,
                       repository: str = "product/runtime") -> tuple[Path, Path, str, dict[str, str]]:
        private, public = self.key_pair(root, "ci-runner", bytes(range(65, 97)))
        policy = root / "runner-policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRunnerTrustPolicy",
            "policyId": "product-ci-runners",
            "maxAttestationLifetimeSeconds": 7200,
            "allowedRunners": [{
                "runnerId": "ci.windows.release",
                "keyId": "ci-windows-release-2026",
                "algorithm": "Ed25519",
                "publicKey": "keys/ci-runner.pem",
                "publicKeySha256": hashlib.sha256(public.read_bytes()).hexdigest(),
                "repositories": [repository],
                "workflows": ["team-contract-acceptance"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": ([{
                "keyId": "ci-windows-release-2026",
                "revokedAt": "2026-08-01T00:00:00Z",
                "reason": "unit test revocation",
            }] if revoked else []),
        }, indent=2) + "\n", encoding="utf-8")
        environment_name = "PDR_TEST_RUNNER_KEY"
        return private, policy, hashlib.sha256(policy.read_bytes()).hexdigest(), \
            dict(os.environ, **{environment_name: str(private)})

    def attest(self, root: Path, report: Path, evidence: Path, junit: Path,
               environment: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], Path]:
        output = root / "runner-attestation.json"
        result = self.run_tool(
            "runner-attest", "--report", str(report), "--evidence", str(evidence),
            "--junit", str(junit), "--runner-id", "ci.windows.release",
            "--repository", "product/runtime", "--source-revision", "1" * 40,
            "--workflow", "team-contract-acceptance", "--job-id", "windows-release",
            "--run-id", "run-1001", "--issued-at", "2026-08-25T12:00:00Z",
            "--lifetime-seconds", "3600", "--key-id", "ci-windows-release-2026",
            "--private-key-environment", "PDR_TEST_RUNNER_KEY", "--output", str(output),
            environment=environment,
        )
        return result, output

    def verify_runner(self, report: Path, evidence: Path, junit: Path,
                      attestation: Path, policy: Path, policy_sha: str,
                      at: str = "2026-08-25T12:30:00Z") -> subprocess.CompletedProcess[str]:
        return self.run_tool(
            "runner-verify", "--attestation", str(attestation),
            "--report", str(report), "--evidence", str(evidence), "--junit", str(junit),
            "--trust-policy", str(policy), "--expected-trust-policy-id",
            "product-ci-runners", "--expected-trust-policy-sha256", policy_sha,
            "--verification-time", at,
        )

    def gate_authorizer_fixture(self, root: Path, revoked: bool = False) \
            -> tuple[Path, Path, str, dict[str, str]]:
        private, public = self.key_pair(root, "gate-authorizer", bytes(range(129, 161)))
        policy = root / "gate-authorization-policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractGateAuthorizationPolicy",
            "policyId": "product-gate-authorizers",
            "maxAuthorizationLifetimeSeconds": 7200,
            "allowedAuthorizers": [{
                "authorizerId": "release.gate.service",
                "keyId": "release-gate-2026",
                "algorithm": "Ed25519",
                "publicKey": "keys/gate-authorizer.pem",
                "publicKeySha256": hashlib.sha256(public.read_bytes()).hexdigest(),
                "registryIds": ["product-contracts"],
                "channels": ["staging", "production"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": ([{
                "keyId": "release-gate-2026",
                "revokedAt": "2026-08-01T00:00:00Z",
                "reason": "unit test revocation",
            }] if revoked else []),
        }, indent=2) + "\n", encoding="utf-8")
        return private, policy, hashlib.sha256(policy.read_bytes()).hexdigest(), \
            dict(os.environ, **{"PDR_TEST_GATE_AUTHORIZER_KEY": str(private)})

    def test_runner_attestation_binds_execution_and_trusted_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report, evidence, junit = self.execution_fixture(root)
            _, policy, policy_sha, environment = self.runner_fixture(root)
            created, attestation = self.attest(root, report, evidence, junit, environment)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            verified = self.verify_runner(
                report, evidence, junit, attestation, policy, policy_sha
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            approval_helper = impact_test.TeamContractImpactGateTests()
            approval_private, approval_policy, approval_policy_sha = \
                approval_helper.approval_fixture(root)
            approval_result, approval = approval_helper.approve(
                root, report, approval_private
            )
            self.assertEqual(
                approval_result.returncode, 0,
                approval_result.stdout + approval_result.stderr,
            )
            ctest = root / ("fake-ctest.cmd" if os.name == "nt" else "fake-ctest")
            gate_report = root / "runner-attested-gate.json"
            gate = subprocess.run([
                sys.executable, str(GATE_TOOL), "gate", "--report", str(report),
                "--evidence", str(evidence), "--junit", str(junit),
                "--ctest", str(ctest), "--test-dir", str(root), "--config", "Release",
                "--approval-policy", str(approval_policy),
                "--expected-approval-policy-id", "product-impact-owners",
                "--expected-approval-policy-sha256", approval_policy_sha,
                "--approval", str(approval), "--runner-attestation", str(attestation),
                "--runner-trust-policy", str(policy),
                "--expected-runner-trust-policy-id", "product-ci-runners",
                "--expected-runner-trust-policy-sha256", policy_sha,
                "--verification-time", "2026-08-25T12:30:00Z",
                "--gate-report", str(gate_report),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            self.assertEqual(
                json.loads(gate_report.read_text(encoding="utf-8"))
                ["runnerAttestation"]["runnerId"],
                "ci.windows.release",
            )
            document = json.loads(attestation.read_text(encoding="utf-8"))
            self.assertEqual(document["sourceRevision"], "1" * 40)
            self.assertEqual(document["junitSha256"], hashlib.sha256(junit.read_bytes()).hexdigest())

    def test_runner_expiry_revocation_scope_and_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report, evidence, junit = self.execution_fixture(root)
            _, policy, policy_sha, environment = self.runner_fixture(root)
            _, attestation = self.attest(root, report, evidence, junit, environment)
            expired = self.verify_runner(
                report, evidence, junit, attestation, policy, policy_sha,
                "2026-08-25T13:30:00Z",
            )
            self.assertEqual(expired.returncode, 2)
            _, revoked_policy, revoked_sha, _ = self.runner_fixture(root / "revoked", True)
            revoked = self.verify_runner(
                report, evidence, junit, attestation, revoked_policy, revoked_sha
            )
            self.assertEqual(revoked.returncode, 2)
            _, wrong_policy, wrong_sha, _ = self.runner_fixture(
                root / "wrong", repository="other/repository"
            )
            wrong = self.verify_runner(
                report, evidence, junit, attestation, wrong_policy, wrong_sha
            )
            self.assertEqual(wrong.returncode, 2)
            evidence.write_bytes(evidence.read_bytes() + b"\n")
            tampered = self.verify_runner(
                report, evidence, junit, attestation, policy, policy_sha
            )
            self.assertEqual(tampered.returncode, 2)

    def test_gate_authorization_replays_gate_and_enforces_registry_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report, evidence, junit = self.execution_fixture(root)
            _, runner_policy, runner_policy_sha, runner_environment = \
                self.runner_fixture(root)
            created, attestation = self.attest(
                root, report, evidence, junit, runner_environment
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            approval_helper = impact_test.TeamContractImpactGateTests()
            approval_private, approval_policy, approval_policy_sha = \
                approval_helper.approval_fixture(root)
            approval_result, approval = approval_helper.approve(
                root, report, approval_private
            )
            self.assertEqual(
                approval_result.returncode, 0,
                approval_result.stdout + approval_result.stderr,
            )
            ctest = root / ("fake-ctest.cmd" if os.name == "nt" else "fake-ctest")
            gate_report = root / "impact-gate.json"
            gate_arguments = [
                "--report", str(report), "--evidence", str(evidence),
                "--junit", str(junit), "--ctest", str(ctest),
                "--test-dir", str(root), "--config", "Release",
                "--approval-policy", str(approval_policy),
                "--expected-approval-policy-id", "product-impact-owners",
                "--expected-approval-policy-sha256", approval_policy_sha,
                "--approval", str(approval),
                "--runner-attestation", str(attestation),
                "--runner-trust-policy", str(runner_policy),
                "--expected-runner-trust-policy-id", "product-ci-runners",
                "--expected-runner-trust-policy-sha256", runner_policy_sha,
                "--verification-time", "2026-08-25T12:30:00Z",
            ]
            gate = subprocess.run([
                sys.executable, str(GATE_TOOL), "gate", *gate_arguments,
                "--gate-report", str(gate_report),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            _, auth_policy, auth_policy_sha, auth_environment = \
                self.gate_authorizer_fixture(root)
            authorization = root / "gate-authorization.json"
            authorized = self.run_tool(
                "gate-authorize", "--gate-report", str(gate_report), *gate_arguments,
                "--registry-id", "product-contracts", "--channel", "staging",
                "--channel", "production", "--authorization-id", "authorization-0001",
                "--authorizer-id", "release.gate.service",
                "--key-id", "release-gate-2026",
                "--private-key-environment", "PDR_TEST_GATE_AUTHORIZER_KEY",
                "--issued-at", "2026-08-25T12:00:00Z",
                "--lifetime-seconds", "3600", "--output", str(authorization),
                environment=auth_environment,
            )
            self.assertEqual(
                authorized.returncode, 0, authorized.stdout + authorized.stderr
            )
            verify_arguments = [
                "gate-authorization-verify", "--gate-report", str(gate_report),
                "--authorization", str(authorization),
                "--authorization-policy", str(auth_policy),
                "--expected-authorization-policy-id", "product-gate-authorizers",
                "--expected-authorization-policy-sha256", auth_policy_sha,
                "--expected-registry-id", "product-contracts",
                "--expected-channel", "production",
                "--verification-time", "2026-08-25T12:30:00Z",
            ]
            verified = self.run_tool(*verify_arguments)
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            original_gate = gate_report.read_bytes()
            forged = json.loads(original_gate)
            forged["approvals"][0]["approverId"] = "forged-owner"
            gate_report.write_text(json.dumps(forged, indent=2) + "\n", encoding="utf-8")
            tampered = self.run_tool(*verify_arguments)
            self.assertEqual(tampered.returncode, 2)
            self.assertIn("different Gate", tampered.stderr)
            gate_report.write_bytes(original_gate)
            wrong_channel = self.run_tool(
                *verify_arguments[:-4], "--expected-channel", "emergency",
                "--verification-time", "2026-08-25T12:30:00Z",
            )
            self.assertEqual(wrong_channel.returncode, 2)
            _, revoked_policy, revoked_sha, _ = self.gate_authorizer_fixture(
                root / "revoked", revoked=True
            )
            revoked_arguments = list(verify_arguments)
            revoked_arguments[revoked_arguments.index("--authorization-policy") + 1] = \
                str(revoked_policy)
            revoked_arguments[
                revoked_arguments.index("--expected-authorization-policy-sha256") + 1
            ] = revoked_sha
            revoked = self.run_tool(*revoked_arguments)
            self.assertEqual(revoked.returncode, 2)

    def anchor_fixture(self, root: Path) -> tuple[Path, Path, str, dict[str, str]]:
        private, public = self.key_pair(root, "audit-anchor", bytes(range(97, 129)))
        policy = root / "anchor-policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRegistryAnchorPolicy",
            "policyId": "product-registry-auditors",
            "allowedAnchors": [{
                "anchorServiceId": "external.audit.service",
                "keyId": "registry-audit-anchor-2026",
                "algorithm": "Ed25519",
                "publicKey": "keys/audit-anchor.pem",
                "publicKeySha256": hashlib.sha256(public.read_bytes()).hexdigest(),
                "registryIds": ["unit-registry"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": [],
        }, indent=2) + "\n", encoding="utf-8")
        return private, policy, hashlib.sha256(policy.read_bytes()).hexdigest(), \
            dict(os.environ, **{"PDR_TEST_ANCHOR_KEY": str(private)})

    def test_external_anchor_accepts_growth_and_detects_whole_registry_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = registry_test.TeamContractRegistryTests()
            registry, package_policy, package_policy_sha, package_environment = \
                helper.initialized(root)
            package = helper.create_package(root, "1.0.0", "1.0.0", package_environment)
            published = helper.publish(registry, package_policy, package_policy_sha, package)
            self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
            _, anchor_policy, anchor_policy_sha, anchor_environment = self.anchor_fixture(
                root / "external-audit"
            )
            anchor = root / "external-audit" / "registry-anchor.json"
            common = registry_test.TeamContractRegistryTests.common(
                registry, package_policy, package_policy_sha
            )[2:]
            created = self.run_tool(
                "registry-anchor", "--registry", str(registry),
                "--anchor-id", "anchor-0001", "--anchor-service-id", "external.audit.service",
                "--key-id", "registry-audit-anchor-2026",
                "--private-key-environment", "PDR_TEST_ANCHOR_KEY",
                "--issued-at", "2026-08-25T12:10:00Z", "--output", str(anchor),
                *common, environment=anchor_environment,
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            verified = self.run_tool(
                "registry-anchor-verify", "--registry", str(registry),
                "--anchor", str(anchor), "--anchor-policy", str(anchor_policy),
                "--expected-anchor-policy-id", "product-registry-auditors",
                "--expected-anchor-policy-sha256", anchor_policy_sha, *common,
                "--verification-time", "2026-08-25T12:30:00Z",
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            initial = next((registry / "revisions").glob("00000000000000000000-*.json"))
            initial_document = json.loads(initial.read_text(encoding="utf-8"))
            rolled_back_pointer = {
                "schemaVersion": 1,
                "product": "PocoDDSRuntimeTeamContractRegistryPointer",
                "registryId": "unit-registry",
                "revision": 0,
                "stateSha256": initial.stem.split("-", 1)[1],
                "updatedAt": initial_document["event"]["occurredAt"],
            }
            (registry / "registry.json").write_text(
                json.dumps(rolled_back_pointer, indent=2) + "\n", encoding="utf-8"
            )
            rollback = self.run_tool(
                "registry-anchor-verify", "--registry", str(registry),
                "--anchor", str(anchor), "--anchor-policy", str(anchor_policy),
                "--expected-anchor-policy-id", "product-registry-auditors",
                "--expected-anchor-policy-sha256", anchor_policy_sha, *common,
                "--verification-time", "2026-08-25T12:30:00Z",
            )
            self.assertEqual(rollback.returncode, 2)
            self.assertIn("older than", rollback.stderr)


if __name__ == "__main__":
    unittest.main()
