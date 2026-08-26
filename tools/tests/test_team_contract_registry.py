#!/usr/bin/env python3

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
PACKAGE_TOOL = TOOLS / "team_contract_package.py"
REGISTRY_TOOL = TOOLS / "team_contract_registry.py"


class TeamContractRegistryTests(unittest.TestCase):
    @staticmethod
    def run_tool(tool: Path, *arguments: str,
                 environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(tool), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    @staticmethod
    def trust_fixture(root: Path) -> tuple[Path, Path, str, dict[str, str]]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        trust = root / "trust"
        keys = trust / "keys"
        keys.mkdir(parents=True)
        private = trust / "publisher.private.pem"
        public = keys / "publisher.pem"
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
        policy = trust / "policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractTrustPolicy",
            "policyId": "registry-unit-policy",
            "allowedPublishers": [{
                "owner": "team.registry-test",
                "keyId": "registry-test-2026",
                "algorithm": "Ed25519",
                "publicKey": "keys/publisher.pem",
                "publicKeySha256": hashlib.sha256(public.read_bytes()).hexdigest(),
                "packageIds": ["team.registry-service"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": [],
        }, indent=2) + "\n", encoding="utf-8")
        environment_name = "PDR_TEST_REGISTRY_PACKAGE_KEY"
        environment = dict(os.environ, **{environment_name: str(private)})
        return policy, private, hashlib.sha256(policy.read_bytes()).hexdigest(), environment

    def create_package(self, root: Path, version: str, service_version: str,
                       environment: dict[str, str]) -> Path:
        contract = root / f"service-{version}-{service_version}.json"
        contract.write_text(json.dumps({
            "schemaVersion": 1,
            "provides": [{
                "contract": "pdr.registry-test",
                "version": service_version,
                "serviceName": "pdr.service.registry-test",
            }],
            "requires": [],
        }, indent=2) + "\n", encoding="utf-8")
        package = root / f"team.registry-service-{version}-{service_version}.pdrcontracts"
        result = self.run_tool(
            PACKAGE_TOOL, "pack", "--package-id", "team.registry-service",
            "--version", version, "--owner", "team.registry-test",
            "--source-date-epoch", "1700000000",
            "--ed25519-private-key-environment", "PDR_TEST_REGISTRY_PACKAGE_KEY",
            "--signing-key-id", "registry-test-2026",
            "--input", f"service-contract={contract}", "--output", str(package),
            environment=environment,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return package

    def create_lock(self, root: Path, package: Path, policy: Path,
                    policy_sha: str, name: str) -> Path:
        lock = root / f"{name}.lock.json"
        result = self.run_tool(
            PACKAGE_TOOL, "lock", "--package", str(package),
            "--require-signature", "--trust-policy", str(policy),
            "--expected-trust-policy-id", "registry-unit-policy",
            "--expected-trust-policy-sha256", policy_sha,
            "--verification-time", "2026-08-25T12:00:00Z",
            "--output", str(lock),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return lock

    @staticmethod
    def impact_gate(root: Path, lock: Path, name: str) -> Path:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        runner_key = Ed25519PrivateKey.from_private_bytes(bytes(range(97, 129)))
        runner_public = root / "runner-keys" / "registry-runner.pem"
        runner_public.parent.mkdir(parents=True, exist_ok=True)
        runner_public.write_bytes(runner_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        runner_policy = root / "runner-policy.json"
        runner_policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRunnerTrustPolicy",
            "policyId": "registry-unit-runners",
            "maxAttestationLifetimeSeconds": 7200,
            "allowedRunners": [{
                "runnerId": "ci.registry-unit",
                "keyId": "registry-unit-runner-2026",
                "algorithm": "Ed25519",
                "publicKey": "keys/registry-runner.pem",
                "publicKeySha256": hashlib.sha256(runner_public.read_bytes()).hexdigest(),
                "repositories": ["product/runtime"],
                "workflows": ["team-contract-acceptance"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": [],
        }, indent=2) + "\n", encoding="utf-8")
        policy_key = root / "keys" / "registry-runner.pem"
        policy_key.parent.mkdir(parents=True, exist_ok=True)
        policy_key.write_bytes(runner_public.read_bytes())
        lock_sha = hashlib.sha256(lock.read_bytes()).hexdigest()
        attestation = {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRunnerAttestation",
            "operation": "team-contract-runner-attest",
            "runnerId": "ci.registry-unit",
            "repository": "product/runtime",
            "sourceRevision": "1" * 40,
            "workflow": "team-contract-acceptance",
            "jobId": "registry-unit",
            "runId": f"{name}-run",
            "issuedAt": "2026-08-25T12:00:00Z",
            "expiresAt": "2026-08-25T13:00:00Z",
            "impactReportSha256": "a" * 64,
            "impactInputSetSha256": "b" * 64,
            "candidateLockSha256": lock_sha,
            "executionEvidenceSha256": "c" * 64,
            "junitSha256": None,
            "ctestExecutableSha256": "d" * 64,
            "ctestCatalogSha256": "e" * 64,
            "ctestCommandSha256": "f" * 64,
            "keyId": "registry-unit-runner-2026",
        }
        payload = json.dumps(
            attestation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        attestation["signature"] = base64.b64encode(runner_key.sign(payload)).decode("ascii")
        attestation_path = root / f"{name}.runner-attestation.json"
        attestation_path.write_text(
            json.dumps(attestation, indent=2) + "\n", encoding="utf-8"
        )
        runner_summary = {
            "attestationSha256": hashlib.sha256(attestation_path.read_bytes()).hexdigest(),
            "policyId": "registry-unit-runners",
            "policySha256": hashlib.sha256(runner_policy.read_bytes()).hexdigest(),
            "runnerId": "ci.registry-unit",
            "repository": "product/runtime",
            "sourceRevision": "1" * 40,
            "workflow": "team-contract-acceptance",
            "jobId": "registry-unit",
            "runId": f"{name}-run",
            "keyId": "registry-unit-runner-2026",
            "publicKeySha256": hashlib.sha256(policy_key.read_bytes()).hexdigest(),
            "issuedAt": "2026-08-25T12:00:00Z",
            "expiresAt": "2026-08-25T13:00:00Z"
        }
        gate = root / f"{name}.gate.json"
        gate.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractImpactGate",
            "operation": "team-contract-impact-gate",
            "passed": True,
            "impactReportSha256": "a" * 64,
            "impactInputSetSha256": "b" * 64,
            "candidateLockSha256": lock_sha,
            "executionEvidenceSha256": "c" * 64,
            "junitSha256": None,
            "runnerAttestation": runner_summary,
            "approvalPolicy": None,
            "requiredOwners": [],
            "approvedOwners": [],
            "approvals": [],
        }, indent=2) + "\n", encoding="utf-8")
        authorizer_key = Ed25519PrivateKey.from_private_bytes(bytes(range(161, 193)))
        authorizer_public = root / "keys" / "gate-authorizer.pem"
        authorizer_public.write_bytes(authorizer_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        authorization_policy = root / "gate-authorization-policy.json"
        authorization_policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractGateAuthorizationPolicy",
            "policyId": "registry-unit-gate-authorizers",
            "maxAuthorizationLifetimeSeconds": 7200,
            "allowedAuthorizers": [{
                "authorizerId": "registry.release.service",
                "keyId": "registry-unit-gate-authorizer-2026",
                "algorithm": "Ed25519",
                "publicKey": "keys/gate-authorizer.pem",
                "publicKeySha256": hashlib.sha256(
                    authorizer_public.read_bytes()
                ).hexdigest(),
                "registryIds": ["unit-registry"],
                "channels": ["staging", "production"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": [],
        }, indent=2) + "\n", encoding="utf-8")
        authorization = {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractGateAuthorization",
            "operation": "team-contract-gate-authorize",
            "decision": "approve",
            "authorizationId": f"{name}-authorization",
            "registryId": "unit-registry",
            "channels": ["production", "staging"],
            "gateReportSha256": hashlib.sha256(gate.read_bytes()).hexdigest(),
            "candidateLockSha256": lock_sha,
            "impactReportSha256": "a" * 64,
            "executionEvidenceSha256": "c" * 64,
            "runnerAttestationSha256": runner_summary["attestationSha256"],
            "issuedAt": "2026-08-25T12:00:00Z",
            "expiresAt": "2026-08-25T13:00:00Z",
            "authorizerId": "registry.release.service",
            "keyId": "registry-unit-gate-authorizer-2026",
        }
        payload = json.dumps(
            authorization, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        authorization["signature"] = base64.b64encode(
            authorizer_key.sign(payload)
        ).decode("ascii")
        (root / f"{name}.gate-authorization.json").write_text(
            json.dumps(authorization, indent=2) + "\n", encoding="utf-8"
        )
        return gate

    @staticmethod
    def common(registry: Path, policy: Path, policy_sha: str) -> list[str]:
        return [
            "--registry", str(registry), "--trust-policy", str(policy),
            "--expected-trust-policy-id", "registry-unit-policy",
            "--expected-trust-policy-sha256", policy_sha,
            "--verification-time", "2026-08-25T12:00:00Z",
        ]

    def initialized(self, root: Path) -> tuple[Path, Path, str, dict[str, str]]:
        policy, _, policy_sha, environment = self.trust_fixture(root)
        registry = root / "registry"
        result = self.run_tool(
            REGISTRY_TOOL, "init", *self.common(registry, policy, policy_sha),
            "--registry-id", "unit-registry", "--actor", "test-admin",
            "--occurred-at", "2026-08-25T12:00:00Z",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return registry, policy, policy_sha, environment

    def publish(self, registry: Path, policy: Path, policy_sha: str,
                package: Path, actor: str = "publisher") -> subprocess.CompletedProcess[str]:
        return self.run_tool(
            REGISTRY_TOOL, "publish", *self.common(registry, policy, policy_sha),
            "--package", str(package), "--actor", actor,
            "--occurred-at", "2026-08-25T12:05:00Z",
        )

    def promote(self, registry: Path, policy: Path, policy_sha: str,
                channel: str, lock: Path, generation: int,
                gate: Path | None = None) -> subprocess.CompletedProcess[str]:
        arguments = [
            "promote", *self.common(registry, policy, policy_sha),
            "--channel", channel, "--lock", str(lock),
            "--expected-generation", str(generation), "--actor", "release-manager",
            "--occurred-at", "2026-08-25T12:10:00Z",
        ]
        if gate:
            name = gate.name.removesuffix(".gate.json")
            runner_policy = gate.parent / "runner-policy.json"
            arguments.extend([
                "--impact-gate", str(gate),
                "--runner-attestation", str(gate.parent / f"{name}.runner-attestation.json"),
                "--runner-trust-policy", str(runner_policy),
                "--expected-runner-trust-policy-id", "registry-unit-runners",
                "--expected-runner-trust-policy-sha256",
                hashlib.sha256(runner_policy.read_bytes()).hexdigest(),
                "--gate-authorization",
                str(gate.parent / f"{name}.gate-authorization.json"),
                "--gate-authorization-policy",
                str(gate.parent / "gate-authorization-policy.json"),
                "--expected-gate-authorization-policy-id",
                "registry-unit-gate-authorizers",
                "--expected-gate-authorization-policy-sha256",
                hashlib.sha256(
                    (gate.parent / "gate-authorization-policy.json").read_bytes()
                ).hexdigest(),
            ])
        return self.run_tool(REGISTRY_TOOL, *arguments)

    def test_publish_promote_resolve_verify_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry, policy, policy_sha, environment = self.initialized(root)
            lease_report = root / "registry-lease.json"
            lease_status = self.run_tool(
                REGISTRY_TOOL, "lease-status", "--registry", str(registry),
                "--report", str(lease_report),
            )
            self.assertEqual(
                lease_status.returncode, 0,
                lease_status.stdout + lease_status.stderr,
            )
            lease_document = json.loads(lease_report.read_bytes())
            self.assertTrue(lease_document["healthy"])
            self.assertFalse(lease_document["active"])
            self.assertEqual(lease_document["epoch"], 1)
            package1 = self.create_package(root, "1.0.0", "1.0.0", environment)
            package2 = self.create_package(root, "1.1.0", "1.1.0", environment)
            lock1 = self.create_lock(root, package1, policy, policy_sha, "release-1")
            lock2 = self.create_lock(root, package2, policy, policy_sha, "release-2")
            for package in (package1, package2):
                published = self.publish(registry, policy, policy_sha, package)
                self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
            gate1 = self.impact_gate(root, lock1, "release-1")
            gate2 = self.impact_gate(root, lock2, "release-2")
            self.assertEqual(self.promote(
                registry, policy, policy_sha, "dev", lock1, 0
            ).returncode, 0)
            staging1 = self.promote(
                registry, policy, policy_sha, "staging", lock1, 0, gate1
            )
            self.assertEqual(staging1.returncode, 0, staging1.stdout + staging1.stderr)
            self.assertEqual(self.promote(
                registry, policy, policy_sha, "production", lock1, 0, gate1
            ).returncode, 0)
            self.assertEqual(self.promote(
                registry, policy, policy_sha, "dev", lock2, 1
            ).returncode, 0)
            self.assertEqual(self.promote(
                registry, policy, policy_sha, "staging", lock2, 1, gate2
            ).returncode, 0)
            self.assertEqual(self.promote(
                registry, policy, policy_sha, "production", lock2, 1, gate2
            ).returncode, 0)
            rollback = self.run_tool(
                REGISTRY_TOOL, "rollback", *self.common(registry, policy, policy_sha),
                "--channel", "production", "--expected-generation", "2",
                "--to-generation", "1", "--actor", "incident-commander",
                "--reason", "restore validated release after incident",
                "--occurred-at", "2026-08-25T12:20:00Z",
            )
            self.assertEqual(rollback.returncode, 0, rollback.stdout + rollback.stderr)
            output = root / "resolved-production"
            report = root / "registry-resolution.json"
            resolved = self.run_tool(
                REGISTRY_TOOL, "resolve", *self.common(registry, policy, policy_sha),
                "--channel", "production", "--output", str(output),
                "--report", str(report),
            )
            self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result["generation"], 3)
            self.assertEqual(result["packages"][0]["version"], "1.0.0")
            verified = self.run_tool(
                REGISTRY_TOOL, "verify", *self.common(registry, policy, policy_sha)
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_same_version_drift_unpublished_lock_and_stale_generation_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry, policy, policy_sha, environment = self.initialized(root)
            package = self.create_package(root, "1.0.0", "1.0.0", environment)
            drift = self.create_package(root, "1.0.0", "1.0.1", environment)
            self.assertEqual(self.publish(
                registry, policy, policy_sha, package
            ).returncode, 0)
            rejected = self.publish(registry, policy, policy_sha, drift)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("same-version", rejected.stderr)
            unpublished = self.create_package(root, "1.1.0", "1.1.0", environment)
            unpublished_lock = self.create_lock(
                root, unpublished, policy, policy_sha, "unpublished"
            )
            missing = self.promote(
                registry, policy, policy_sha, "dev", unpublished_lock, 0
            )
            self.assertEqual(missing.returncode, 2)
            lock = self.create_lock(root, package, policy, policy_sha, "release")
            self.assertEqual(self.promote(
                registry, policy, policy_sha, "dev", lock, 0
            ).returncode, 0)
            stale = self.promote(registry, policy, policy_sha, "dev", lock, 0)
            self.assertEqual(stale.returncode, 2)
            self.assertIn("generation changed", stale.stderr)

    def test_non_development_promotion_requires_gate_and_predecessor_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry, policy, policy_sha, environment = self.initialized(root)
            package1 = self.create_package(root, "1.0.0", "1.0.0", environment)
            package2 = self.create_package(root, "1.1.0", "1.1.0", environment)
            for package in (package1, package2):
                self.assertEqual(self.publish(
                    registry, policy, policy_sha, package
                ).returncode, 0)
            lock1 = self.create_lock(root, package1, policy, policy_sha, "release-1")
            lock2 = self.create_lock(root, package2, policy, policy_sha, "release-2")
            self.assertEqual(self.promote(
                registry, policy, policy_sha, "dev", lock1, 0
            ).returncode, 0)
            no_gate = self.promote(
                registry, policy, policy_sha, "staging", lock1, 0
            )
            self.assertEqual(no_gate.returncode, 2)
            forged_owner_gate = self.impact_gate(root, lock1, "release-1-owner")
            forged_owner_document = json.loads(
                forged_owner_gate.read_text(encoding="utf-8")
            )
            forged_owner_document["requiredOwners"] = ["team.forged"]
            forged_owner_document["approvedOwners"] = ["team.forged"]
            forged_owner_gate.write_text(
                json.dumps(forged_owner_document, indent=2) + "\n", encoding="utf-8"
            )
            forged_owner = self.promote(
                registry, policy, policy_sha, "staging", lock1, 0,
                forged_owner_gate,
            )
            self.assertEqual(forged_owner.returncode, 2)
            self.assertIn("different Gate", forged_owner.stderr)
            forged_gate = self.impact_gate(root, lock1, "release-1-runner")
            forged_document = json.loads(forged_gate.read_text(encoding="utf-8"))
            forged_document["runnerAttestation"]["runnerId"] = "ci.forged"
            forged_gate.write_text(
                json.dumps(forged_document, indent=2) + "\n", encoding="utf-8"
            )
            forged = self.promote(
                registry, policy, policy_sha, "staging", lock1, 0, forged_gate
            )
            self.assertEqual(forged.returncode, 2)
            self.assertIn("does not match", forged.stderr)
            wrong = self.promote(
                registry, policy, policy_sha, "staging", lock2, 0,
                self.impact_gate(root, lock2, "release-2"),
            )
            self.assertEqual(wrong.returncode, 2)
            self.assertIn("current dev lock", wrong.stderr)

    def test_tampered_blob_breaks_verification_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry, policy, policy_sha, environment = self.initialized(root)
            package = self.create_package(root, "1.0.0", "1.0.0", environment)
            self.assertEqual(self.publish(
                registry, policy, policy_sha, package
            ).returncode, 0)
            pointer = json.loads((registry / "registry.json").read_text(encoding="utf-8"))
            state_path = registry / "revisions" / (
                f"{pointer['revision']:020d}-{pointer['stateSha256']}.json"
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            blob = registry / state["packages"][0]["blob"]
            blob.write_bytes(blob.read_bytes() + b"tampered")
            verified = self.run_tool(
                REGISTRY_TOOL, "verify", *self.common(registry, policy, policy_sha)
            )
            self.assertEqual(verified.returncode, 2)
            self.assertIn("blob changed", verified.stderr)
            blocked = self.publish(registry, policy, policy_sha, package)
            self.assertEqual(blocked.returncode, 2)


if __name__ == "__main__":
    unittest.main()
