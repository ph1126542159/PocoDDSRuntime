#!/usr/bin/env python3

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
REMOTE_TOOL = TOOLS / "team_contract_registry_remote.py"
ACCESS_POLICY_TOOL = TOOLS / "team_contract_registry_access_policy.py"
PDR_TOOL = TOOLS / "pdr.py"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TOOLS))
import test_team_contract_registry as registry_test  # noqa: E402
import team_contract_registry_remote as remote_tool  # noqa: E402


class TeamContractRegistryRemoteTests(unittest.TestCase):
    @staticmethod
    def free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    @staticmethod
    def run_remote(*arguments: str,
                   environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(REMOTE_TOOL), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    @staticmethod
    def access_policy(root: Path) -> tuple[Path, str, dict[str, str]]:
        tokens = {
            "publisher": "publisher-unit-token-0123456789abcdef-2026",
            "promoter": "promoter-unit-token-0123456789abcdef-2026",
            "reader": "reader-unit-token-0123456789abcdef-2026",
            "limited": "limited-unit-token-0123456789abcdef-2026",
            "devonly": "devonly-unit-token-0123456789abcdef-2026",
            "auditor": "auditor-unit-token-0123456789abcdef-2026",
            "operator": "operator-unit-token-0123456789abcdef-2026",
            "revoked": "revoked-unit-token-0123456789abcdef-2026",
        }
        policy = root / "remote-access-policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRegistryAccessPolicy",
            "policyId": "registry-unit-remote-access",
            "registryId": "unit-registry",
            "maxRequestBytes": 4 * 1024 * 1024,
            "maxResponseBytes": 4 * 1024 * 1024,
            "principals": [{
                "principalId": "team.registry-publisher",
                "tokenSha256": hashlib.sha256(tokens["publisher"].encode()).hexdigest(),
                "roles": ["publisher"],
                "packageIds": ["team.registry-service"],
                "channels": [],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }, {
                "principalId": "product.release-manager",
                "tokenSha256": hashlib.sha256(tokens["promoter"].encode()).hexdigest(),
                "roles": ["promoter", "rollback"],
                "packageIds": [],
                "channels": ["dev", "staging", "production"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }, {
                "principalId": "team.registry-consumer",
                "tokenSha256": hashlib.sha256(tokens["reader"].encode()).hexdigest(),
                "roles": ["reader"],
                "packageIds": [],
                "channels": [],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }, {
                "principalId": "team.other-publisher",
                "tokenSha256": hashlib.sha256(tokens["limited"].encode()).hexdigest(),
                "roles": ["publisher"],
                "packageIds": ["team.other-service"],
                "channels": [],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }, {
                "principalId": "product.dev-promoter",
                "tokenSha256": hashlib.sha256(tokens["devonly"].encode()).hexdigest(),
                "roles": ["promoter"],
                "packageIds": [],
                "channels": ["dev"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }, {
                "principalId": "product.registry-auditor",
                "tokenSha256": hashlib.sha256(tokens["auditor"].encode()).hexdigest(),
                "roles": ["auditor"],
                "packageIds": [],
                "channels": [],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }, {
                "principalId": "product.registry-operator",
                "tokenSha256": hashlib.sha256(tokens["operator"].encode()).hexdigest(),
                "roles": ["operator"],
                "packageIds": [],
                "channels": [],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }, {
                "principalId": "team.revoked-consumer",
                "tokenSha256": hashlib.sha256(tokens["revoked"].encode()).hexdigest(),
                "roles": ["reader"],
                "packageIds": [],
                "channels": [],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedTokenSha256": [
                hashlib.sha256(tokens["revoked"].encode()).hexdigest()
            ],
        }, indent=2) + "\n", encoding="utf-8")
        environment = dict(os.environ)
        for name, token in tokens.items():
            environment[f"PDR_TEST_REMOTE_{name.upper()}_TOKEN"] = token
        return policy, hashlib.sha256(policy.read_bytes()).hexdigest(), environment

    @staticmethod
    def audit_policy(root: Path, environment: dict[str, str]) -> tuple[Path, str]:
        trust = root / "remote-audit-trust"
        keys = trust / "keys"
        keys.mkdir(parents=True)
        public = keys / "auditor.pem"
        public.write_bytes((root / "trust" / "keys" / "publisher.pem").read_bytes())
        environment["PDR_TEST_REMOTE_AUDIT_KEY"] = str(
            root / "trust" / "publisher.private.pem"
        )
        policy = trust / "policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRegistryRemoteAuditPolicy",
            "policyId": "registry-unit-remote-auditors",
            "auditors": [{
                "auditorId": "external.registry-auditor",
                "keyId": "registry-audit-2026",
                "algorithm": "Ed25519",
                "publicKey": "keys/auditor.pem",
                "publicKeySha256": hashlib.sha256(public.read_bytes()).hexdigest(),
                "registryIds": ["unit-registry"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": [],
        }, indent=2) + "\n", encoding="utf-8")
        return policy, hashlib.sha256(policy.read_bytes()).hexdigest()

    @staticmethod
    def access_policy_signer(
            root: Path, environment: dict[str, str]) -> tuple[Path, str]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        trust = root / "remote-access-policy-trust"
        keys = trust / "keys"
        keys.mkdir(parents=True)
        private = trust / "signer.private.pem"
        public = keys / "signer.pem"
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(33, 65)))
        private.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        public.write_bytes(key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        environment["PDR_TEST_REMOTE_ACCESS_POLICY_KEY"] = str(private)
        policy = trust / "policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRegistryAccessPolicyTrustPolicy",
            "policyId": "registry-unit-access-policy-signers",
            "allowedSigners": [{
                "keyId": "registry-access-policy-2026",
                "algorithm": "Ed25519",
                "publicKey": "keys/signer.pem",
                "publicKeySha256": hashlib.sha256(public.read_bytes()).hexdigest(),
                "registryIds": ["unit-registry"],
                "policyIds": ["registry-unit-remote-access"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": [],
        }, indent=2) + "\n", encoding="utf-8")
        return policy, hashlib.sha256(policy.read_bytes()).hexdigest()

    @staticmethod
    def wait_server(process: subprocess.Popen[str], port: int) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise AssertionError(f"remote server exited:\n{stdout}\n{stderr}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.05)
        raise AssertionError("remote Registry server did not listen")

    def test_remote_rbac_idempotency_revision_and_path_free_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = registry_test.TeamContractRegistryTests()
            registry, trust_policy, trust_sha, package_environment = helper.initialized(root)
            package = helper.create_package(
                root, "1.0.0", "1.0.0", package_environment
            )
            lock = helper.create_lock(root, package, trust_policy, trust_sha, "release")
            gate = helper.impact_gate(root, lock, "release")
            access_policy, access_sha, environment = self.access_policy(root)
            audit_policy, audit_policy_sha = self.audit_policy(root, environment)
            access_signer_policy, access_signer_policy_sha = \
                self.access_policy_signer(root, environment)
            (root / "external-audit-archives").mkdir()
            port = self.free_port()
            server = subprocess.Popen([
                sys.executable, str(REMOTE_TOOL), "serve",
                "--registry", str(registry), "--bind", "127.0.0.1",
                "--port", str(port), "--allow-insecure-loopback", "--quiet",
                "--control-directory", str(root / "remote-control"),
                "--audit-archive-directory", str(root / "external-audit-archives"),
                "--access-policy", str(access_policy),
                "--expected-access-policy-id", "registry-unit-remote-access",
                "--expected-access-policy-sha256", access_sha,
                "--access-policy-trust-policy", str(access_signer_policy),
                "--expected-access-policy-trust-policy-id",
                    "registry-unit-access-policy-signers",
                "--expected-access-policy-trust-policy-sha256",
                    access_signer_policy_sha,
                "--trust-policy", str(trust_policy),
                "--expected-trust-policy-id", "registry-unit-policy",
                "--expected-trust-policy-sha256", trust_sha,
                "--runner-trust-policy", str(root / "runner-policy.json"),
                "--expected-runner-trust-policy-id", "registry-unit-runners",
                "--expected-runner-trust-policy-sha256",
                    hashlib.sha256((root / "runner-policy.json").read_bytes()).hexdigest(),
                "--gate-authorization-policy", str(root / "gate-authorization-policy.json"),
                "--expected-gate-authorization-policy-id",
                    "registry-unit-gate-authorizers",
                "--expected-gate-authorization-policy-sha256",
                    hashlib.sha256(
                        (root / "gate-authorization-policy.json").read_bytes()
                    ).hexdigest(),
                "--verification-time", "2026-08-25T12:00:00Z",
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.wait_server(server, port)
                common = [
                    "--url", f"http://127.0.0.1:{port}",
                    "--registry-id", "unit-registry", "--allow-insecure-loopback",
                ]
                wrong_package_scope = self.run_remote(
                    "publish", *common, "--request-id", "wrong-scope-0001",
                    "--token-environment", "PDR_TEST_REMOTE_LIMITED_TOKEN",
                    "--expected-revision", "0", "--package", str(package),
                    environment=environment,
                )
                self.assertEqual(wrong_package_scope.returncode, 2)
                self.assertIn("does not own", wrong_package_scope.stderr)
                revoked = self.run_remote(
                    "verify", *common, "--request-id", "revoked-0001",
                    "--token-environment", "PDR_TEST_REMOTE_REVOKED_TOKEN",
                    environment=environment,
                )
                self.assertEqual(revoked.returncode, 2)
                self.assertIn("revoked", revoked.stderr)
                tampered_package = root / "tampered.pdrcontracts"
                tampered_package.write_bytes(package.read_bytes() + b"tampered")
                tampered = self.run_remote(
                    "publish", *common, "--request-id", "tampered-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", "0", "--package", str(tampered_package),
                    environment=environment,
                )
                self.assertEqual(tampered.returncode, 2)
                oversized_package = root / "oversized.pdrcontracts"
                oversized_package.write_bytes(b"x" * (4 * 1024 * 1024))
                oversized = self.run_remote(
                    "publish", *common, "--request-id", "oversized-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", "0", "--package", str(oversized_package),
                    environment=environment,
                )
                self.assertEqual(oversized.returncode, 2)
                published = self.run_remote(
                    "publish", *common, "--request-id", "publish-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", "0", "--package", str(package),
                    environment=environment,
                )
                self.assertEqual(
                    published.returncode, 0, published.stdout + published.stderr
                )
                replayed = self.run_remote(
                    "publish", *common, "--request-id", "publish-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", "0", "--package", str(package),
                    environment=environment,
                )
                self.assertEqual(replayed.returncode, 0, replayed.stdout + replayed.stderr)
                reused = self.run_remote(
                    "publish", *common, "--request-id", "publish-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", "1", "--package", str(package),
                    environment=environment,
                )
                self.assertEqual(reused.returncode, 2)
                self.assertIn("different content", reused.stderr)
                stale = self.run_remote(
                    "publish", *common, "--request-id", "publish-0002",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", "0", "--package", str(package),
                    environment=environment,
                )
                self.assertEqual(stale.returncode, 2)
                self.assertIn("rejected", stale.stderr)
                denied = self.run_remote(
                    "promote", *common, "--request-id", "denied-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", "1", "--channel", "dev",
                    "--expected-generation", "0", "--lock", str(lock),
                    environment=environment,
                )
                self.assertEqual(denied.returncode, 2)
                self.assertIn("role", denied.stderr)
                dev = self.run_remote(
                    "promote", *common, "--request-id", "promote-dev-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PROMOTER_TOKEN",
                    "--expected-revision", "1", "--channel", "dev",
                    "--expected-generation", "0", "--lock", str(lock),
                    environment=environment,
                )
                self.assertEqual(dev.returncode, 0, dev.stdout + dev.stderr)
                wrong_channel = self.run_remote(
                    "promote", *common, "--request-id", "wrong-channel-0001",
                    "--token-environment", "PDR_TEST_REMOTE_DEVONLY_TOKEN",
                    "--expected-revision", "2", "--channel", "staging",
                    "--expected-generation", "0", "--lock", str(lock),
                    "--impact-gate", str(gate),
                    "--runner-attestation", str(root / "release.runner-attestation.json"),
                    "--gate-authorization", str(root / "release.gate-authorization.json"),
                    environment=environment,
                )
                self.assertEqual(wrong_channel.returncode, 2)
                self.assertIn("does not own", wrong_channel.stderr)
                pending_command = {
                    "schemaVersion": 1,
                    "product": remote_tool.COMMAND_PRODUCT,
                    "operation": "publish",
                    "registryId": "unit-registry",
                    "expectedRevision": 1,
                    "parameters": {},
                    "artifacts": {"package": remote_tool.artifact(str(package))},
                }
                pending_path = remote_tool.request_record_path(
                    root / "remote-control", "pending-0001"
                )
                remote_tool.registry_tool.exclusive_bytes(
                    pending_path,
                    remote_tool.package_tool.json_bytes({
                        "schemaVersion": 1,
                        "requestId": "pending-0001",
                        "requestSha256": remote_tool.canonical_sha(pending_command),
                        "principalId": "team.registry-publisher",
                        "operation": "publish",
                        "startedRevision": 1,
                        "status": "pending",
                    }),
                )
                uncertain = self.run_remote(
                    "publish", *common, "--request-id", "pending-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", "1", "--package", str(package),
                    environment=environment,
                )
                self.assertEqual(uncertain.returncode, 2)
                self.assertIn("operator recovery required", uncertain.stderr)
                pending_status = self.run_remote(
                    "status", *common, "--request-id", "pending-0001",
                    "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(
                    pending_status.returncode, 0,
                    pending_status.stdout + pending_status.stderr,
                )
                self.assertIn("status=pending", pending_status.stdout)
                recovered_uncertain = self.run_remote(
                    "recover", *common, "--recovery-id", "recovery-uncertain-0001",
                    "--target-request-id", "pending-0001",
                    "--target-request-sha256", remote_tool.canonical_sha(pending_command),
                    "--expected-started-revision", "1",
                    "--expected-current-revision", "2",
                    "--disposition", "uncertain",
                    "--reason", "Registry revision advanced before response durability",
                    "--token-environment", "PDR_TEST_REMOTE_OPERATOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(
                    recovered_uncertain.returncode, 0,
                    recovered_uncertain.stdout + recovered_uncertain.stderr,
                )
                replayed_recovery = self.run_remote(
                    "recover", *common, "--recovery-id", "recovery-uncertain-0001",
                    "--target-request-id", "pending-0001",
                    "--target-request-sha256", remote_tool.canonical_sha(pending_command),
                    "--expected-started-revision", "1",
                    "--expected-current-revision", "2",
                    "--disposition", "uncertain",
                    "--reason", "Registry revision advanced before response durability",
                    "--token-environment", "PDR_TEST_REMOTE_OPERATOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(replayed_recovery.returncode, 0)
                terminal_retry = self.run_remote(
                    "publish", *common, "--request-id", "pending-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", "1", "--package", str(package),
                    environment=environment,
                )
                self.assertEqual(terminal_retry.returncode, 2)
                self.assertIn("terminal after operator recovery", terminal_retry.stderr)

                abort_command = {
                    "schemaVersion": 1,
                    "product": remote_tool.COMMAND_PRODUCT,
                    "operation": "publish",
                    "registryId": "unit-registry",
                    "expectedRevision": 2,
                    "parameters": {},
                    "artifacts": {"package": remote_tool.artifact(str(package))},
                }
                abort_path = remote_tool.request_record_path(
                    root / "remote-control", "pending-abort-0001"
                )
                remote_tool.registry_tool.exclusive_bytes(
                    abort_path,
                    remote_tool.package_tool.json_bytes({
                        "schemaVersion": 1,
                        "requestId": "pending-abort-0001",
                        "requestSha256": remote_tool.canonical_sha(abort_command),
                        "principalId": "team.registry-publisher",
                        "operation": "publish",
                        "startedRevision": 2,
                        "status": "pending",
                    }),
                )
                wrong_disposition = self.run_remote(
                    "recover", *common, "--recovery-id", "recovery-wrong-0001",
                    "--target-request-id", "pending-abort-0001",
                    "--target-request-sha256", remote_tool.canonical_sha(abort_command),
                    "--expected-started-revision", "2",
                    "--expected-current-revision", "2",
                    "--disposition", "uncertain", "--reason", "wrong disposition",
                    "--token-environment", "PDR_TEST_REMOTE_OPERATOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(wrong_disposition.returncode, 2)
                self.assertIn("must be explicitly aborted", wrong_disposition.stderr)
                recovered_aborted = subprocess.run(
                    [sys.executable, str(PDR_TOOL), "contract-package",
                     "registry-remote-recover", *common,
                     "--recovery-id", "recovery-abort-0001",
                     "--target-request-id", "pending-abort-0001",
                     "--target-request-sha256", remote_tool.canonical_sha(abort_command),
                     "--expected-started-revision", "2",
                     "--expected-current-revision", "2",
                     "--disposition", "aborted",
                     "--reason", "No Registry revision was committed",
                     "--token-environment", "PDR_TEST_REMOTE_OPERATOR_TOKEN"],
                    check=False, capture_output=True, text=True, env=environment,
                )
                self.assertEqual(
                    recovered_aborted.returncode, 0,
                    recovered_aborted.stdout + recovered_aborted.stderr,
                )
                staging = self.run_remote(
                    "promote", *common, "--request-id", "promote-staging-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PROMOTER_TOKEN",
                    "--expected-revision", "2", "--channel", "staging",
                    "--expected-generation", "0", "--lock", str(lock),
                    "--impact-gate", str(gate),
                    "--runner-attestation", str(root / "release.runner-attestation.json"),
                    "--gate-authorization", str(root / "release.gate-authorization.json"),
                    environment=environment,
                )
                self.assertEqual(staging.returncode, 0, staging.stdout + staging.stderr)
                output = root / "remote-resolution"
                resolution_report = root / "remote-resolution-report.json"
                resolved = self.run_remote(
                    "resolve", *common, "--request-id", "resolve-0001",
                    "--token-environment", "PDR_TEST_REMOTE_READER_TOKEN",
                    "--channel", "staging", "--output", str(output),
                    "--report", str(resolution_report),
                    environment=environment,
                )
                self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)
                self.assertTrue(output.is_dir())
                self.assertTrue(any(path.is_file() for path in output.rglob("*")))
                serialized_report = resolution_report.read_text(encoding="utf-8")
                self.assertNotIn(str(registry), serialized_report)
                self.assertNotIn("pdr-remote-registry-", serialized_report)
                verified = subprocess.run(
                    [sys.executable, str(PDR_TOOL), "contract-package",
                     "registry-remote-verify", *common,
                     "--request-id", "verify-0001", "--token-environment",
                     "PDR_TEST_REMOTE_READER_TOKEN"],
                    check=False, capture_output=True, text=True, env=environment,
                )
                self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
                audit_verified = subprocess.run(
                    [sys.executable, str(PDR_TOOL), "contract-package",
                     "registry-remote-audit-verify", *common,
                     "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN"],
                    check=False, capture_output=True, text=True, env=environment,
                )
                self.assertEqual(
                    audit_verified.returncode, 0,
                    audit_verified.stdout + audit_verified.stderr,
                )
                checkpoint = root / "external-audit" / "checkpoint-0001.json"
                created_checkpoint = self.run_remote(
                    "audit-checkpoint", "--control-directory",
                    str(root / "remote-control"), "--registry-id", "unit-registry",
                    "--checkpoint-id", "checkpoint-0001",
                    "--auditor-id", "external.registry-auditor",
                    "--key-id", "registry-audit-2026",
                    "--private-key-environment", "PDR_TEST_REMOTE_AUDIT_KEY",
                    "--issued-at", "2026-08-25T13:00:00Z",
                    "--output", str(checkpoint), environment=environment,
                )
                self.assertEqual(
                    created_checkpoint.returncode, 0,
                    created_checkpoint.stdout + created_checkpoint.stderr,
                )
                verified_checkpoint = self.run_remote(
                    "audit-checkpoint-verify", "--control-directory",
                    str(root / "remote-control"), "--registry-id", "unit-registry",
                    "--checkpoint", str(checkpoint),
                    "--audit-policy", str(audit_policy),
                    "--expected-audit-policy-id", "registry-unit-remote-auditors",
                    "--expected-audit-policy-sha256", audit_policy_sha,
                    "--verification-time", "2026-08-25T13:01:00Z",
                    environment=environment,
                )
                self.assertEqual(
                    verified_checkpoint.returncode, 0,
                    verified_checkpoint.stdout + verified_checkpoint.stderr,
                )
                revoked_policy = root / "remote-audit-trust" / "revoked-policy.json"
                revoked_document = json.loads(audit_policy.read_text(encoding="utf-8"))
                revoked_document["revokedKeys"] = [{
                    "keyId": "registry-audit-2026",
                    "revokedAt": "2026-08-25T13:00:30Z",
                    "reason": "unit-test revocation",
                }]
                revoked_policy.write_text(
                    json.dumps(revoked_document, indent=2) + "\n", encoding="utf-8"
                )
                revoked_checkpoint = self.run_remote(
                    "audit-checkpoint-verify", "--control-directory",
                    str(root / "remote-control"), "--registry-id", "unit-registry",
                    "--checkpoint", str(checkpoint),
                    "--audit-policy", str(revoked_policy),
                    "--expected-audit-policy-id", "registry-unit-remote-auditors",
                    "--expected-audit-policy-sha256",
                    hashlib.sha256(revoked_policy.read_bytes()).hexdigest(),
                    "--verification-time", "2026-08-25T13:01:00Z",
                    environment=environment,
                )
                self.assertEqual(revoked_checkpoint.returncode, 2)
                self.assertIn("revoked", revoked_checkpoint.stderr)

                checkpoint_document = json.loads(checkpoint.read_bytes())
                archive_directory = root / "external-audit-archives"
                archive = archive_directory / "audit-0001.pdraudit"
                archive_report = root / "audit-archive-create.json"
                created_archive = subprocess.run([
                    sys.executable, str(PDR_TOOL), "contract-package",
                    "registry-remote-audit-archive-create",
                    "--control-directory", str(root / "remote-control"),
                    "--audit-archive-directory", str(archive_directory),
                    "--registry-id", "unit-registry",
                    "--archive-id", "audit-archive-0001",
                    "--checkpoint", str(checkpoint),
                    "--audit-policy", str(audit_policy),
                    "--expected-audit-policy-id", "registry-unit-remote-auditors",
                    "--expected-audit-policy-sha256", audit_policy_sha,
                    "--verification-time", "2026-08-25T13:01:00Z",
                    "--created-at", "2026-08-25T13:02:00Z",
                    "--output", str(archive), "--report", str(archive_report),
                ], check=False, capture_output=True, text=True, env=environment)
                self.assertEqual(
                    created_archive.returncode, 0,
                    created_archive.stdout + created_archive.stderr,
                )
                verified_archive = subprocess.run([
                    sys.executable, str(PDR_TOOL), "contract-package",
                    "registry-remote-audit-archive-verify",
                    "--control-directory", str(root / "remote-control"),
                    "--audit-archive-directory", str(archive_directory),
                    "--registry-id", "unit-registry",
                    "--audit-policy", str(audit_policy),
                    "--expected-audit-policy-id", "registry-unit-remote-auditors",
                    "--expected-audit-policy-sha256", audit_policy_sha,
                    "--verification-time", "2026-08-25T13:02:30Z",
                ], check=False, capture_output=True, text=True, env=environment)
                self.assertEqual(
                    verified_archive.returncode, 0,
                    verified_archive.stdout + verified_archive.stderr,
                )
                archive_status = self.run_remote(
                    "audit-archive-status", *common,
                    "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(
                    archive_status.returncode, 0,
                    archive_status.stdout + archive_status.stderr,
                )
                pruned_archive = subprocess.run([
                    sys.executable, str(PDR_TOOL), "contract-package",
                    "registry-remote-audit-archive-prune",
                    "--control-directory", str(root / "remote-control"),
                    "--audit-archive-directory", str(archive_directory),
                    "--registry-id", "unit-registry",
                    "--expected-through-sequence",
                    str(checkpoint_document["auditSequence"]),
                    "--expected-through-record-sha256",
                    checkpoint_document["auditRecordSha256"], "--confirm-prune",
                ], check=False, capture_output=True, text=True, env=environment)
                self.assertEqual(
                    pruned_archive.returncode, 0,
                    pruned_archive.stdout + pruned_archive.stderr,
                )
                self.assertFalse(list(
                    (root / "remote-control" / "audit" / "records").glob(
                        f"{checkpoint_document['auditSequence']:020d}-*.json"
                    )
                ))
                replay_after_prune = self.run_remote(
                    "verify", *common, "--request-id", "verify-0001",
                    "--token-environment", "PDR_TEST_REMOTE_READER_TOKEN",
                    environment=environment,
                )
                self.assertEqual(
                    replay_after_prune.returncode, 0,
                    replay_after_prune.stdout + replay_after_prune.stderr,
                )
                prune_retry = subprocess.run([
                    sys.executable, str(PDR_TOOL), "contract-package",
                    "registry-remote-audit-archive-prune",
                    "--control-directory", str(root / "remote-control"),
                    "--audit-archive-directory", str(archive_directory),
                    "--registry-id", "unit-registry",
                    "--expected-through-sequence",
                    str(checkpoint_document["auditSequence"]),
                    "--expected-through-record-sha256",
                    checkpoint_document["auditRecordSha256"], "--confirm-prune",
                ], check=False, capture_output=True, text=True, env=environment)
                self.assertEqual(prune_retry.returncode, 0)
                self.assertIn("records=0", prune_retry.stdout)

                archive_bytes = archive.read_bytes()
                archive.write_bytes(archive_bytes + b"tampered")
                tampered_archive = self.run_remote(
                    "audit-verify", *common,
                    "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(tampered_archive.returncode, 2)
                self.assertIn("archive digest changed", tampered_archive.stderr)
                archive.write_bytes(archive_bytes)
                print(
                    "PDR_AUDIT_ARCHIVE_RECOVERY_PASS archive=1 prune=1 "
                    "idempotency=1 tamper=1 retry=1"
                )

                initial_access_bytes = access_policy.read_bytes()
                rotated_draft = root / "rotated-access-policy-draft.json"
                rotated_document = json.loads(initial_access_bytes)
                rotated_document["revokedTokenSha256"].append(
                    hashlib.sha256(
                        environment["PDR_TEST_REMOTE_READER_TOKEN"].encode()
                    ).hexdigest()
                )
                rotated_draft.write_text(
                    json.dumps(rotated_document, indent=2) + "\n", encoding="utf-8"
                )
                rotated_policy = root / "rotated-access-policy.json"
                signed_rotation = subprocess.run([
                    sys.executable, str(ACCESS_POLICY_TOOL), "sign",
                    "--input", str(rotated_draft),
                    "--expected-previous-policy-sha256", access_sha,
                    "--policy-revision", "1",
                    "--issued-at", "2026-08-25T11:59:00Z",
                    "--key-id", "registry-access-policy-2026",
                    "--private-key-environment", "PDR_TEST_REMOTE_ACCESS_POLICY_KEY",
                    "--max-active-request-records", "1",
                    "--output", str(rotated_policy),
                ], check=False, capture_output=True, text=True, env=environment)
                self.assertEqual(
                    signed_rotation.returncode, 0,
                    signed_rotation.stdout + signed_rotation.stderr,
                )
                activated_rotation = subprocess.run([
                    sys.executable, str(PDR_TOOL), "contract-package",
                    "registry-access-policy-activate",
                    "--active-policy", str(access_policy),
                    "--candidate", str(rotated_policy),
                    "--expected-current-policy-sha256", access_sha,
                    "--trust-policy", str(access_signer_policy),
                    "--expected-trust-policy-id",
                        "registry-unit-access-policy-signers",
                    "--expected-trust-policy-sha256", access_signer_policy_sha,
                    "--verification-time", "2026-08-25T13:03:00Z",
                ], check=False, capture_output=True, text=True, env=environment)
                self.assertEqual(
                    activated_rotation.returncode, 0,
                    activated_rotation.stdout + activated_rotation.stderr,
                )
                rotated_bytes = access_policy.read_bytes()
                rotated_sha = hashlib.sha256(rotated_bytes).hexdigest()
                capacity_report = root / "remote-capacity.json"
                capacity = subprocess.run([
                    sys.executable, str(PDR_TOOL), "contract-package",
                    "registry-remote-capacity", *common,
                    "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN",
                    "--report", str(capacity_report),
                ], check=False, capture_output=True, text=True, env=environment)
                self.assertEqual(capacity.returncode, 0, capacity.stdout + capacity.stderr)
                capacity_document = json.loads(capacity_report.read_bytes())
                self.assertEqual(capacity_document["policyRevision"], 1)
                self.assertFalse(capacity_document["acceptingMutations"])
                self.assertEqual(
                    capacity_document["limits"]["maxActiveRequestRecords"], 1
                )
                revoked_reader_after_reload = self.run_remote(
                    "verify", *common, "--request-id", "revoked-after-reload-0001",
                    "--token-environment", "PDR_TEST_REMOTE_READER_TOKEN",
                    environment=environment,
                )
                self.assertEqual(revoked_reader_after_reload.returncode, 2)
                self.assertIn("revoked", revoked_reader_after_reload.stderr)
                capacity_rejected = self.run_remote(
                    "publish", *common, "--request-id", "capacity-full-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", "3", "--package", str(package),
                    environment=environment,
                )
                self.assertEqual(capacity_rejected.returncode, 2)
                self.assertIn("capacity would be exceeded", capacity_rejected.stderr)

                skipped_policy = root / "skipped-access-policy.json"
                skipped_sign = self.run_remote(
                    "audit-verify", *common,
                    "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(skipped_sign.returncode, 0)
                signed_skip = subprocess.run([
                    sys.executable, str(ACCESS_POLICY_TOOL), "sign",
                    "--input", str(rotated_draft),
                    "--expected-previous-policy-sha256", rotated_sha,
                    "--policy-revision", "3",
                    "--issued-at", "2026-08-25T11:59:30Z",
                    "--key-id", "registry-access-policy-2026",
                    "--private-key-environment", "PDR_TEST_REMOTE_ACCESS_POLICY_KEY",
                    "--output", str(skipped_policy),
                ], check=False, capture_output=True, text=True, env=environment)
                self.assertEqual(signed_skip.returncode, 0)
                rejected_skip = subprocess.run([
                    sys.executable, str(ACCESS_POLICY_TOOL), "activate",
                    "--active-policy", str(access_policy),
                    "--candidate", str(skipped_policy),
                    "--expected-current-policy-sha256", rotated_sha,
                    "--trust-policy", str(access_signer_policy),
                    "--expected-trust-policy-id",
                        "registry-unit-access-policy-signers",
                    "--expected-trust-policy-sha256", access_signer_policy_sha,
                    "--verification-time", "2026-08-25T13:05:00Z",
                ], check=False, capture_output=True, text=True, env=environment)
                self.assertEqual(rejected_skip.returncode, 2)
                self.assertIn("exact successor", rejected_skip.stderr)

                access_policy.write_bytes(initial_access_bytes)
                rollback_rejected = self.run_remote(
                    "capacity", *common,
                    "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(rollback_rejected.returncode, 2)
                self.assertIn("reload failed closed", rollback_rejected.stderr)
                access_policy.write_bytes(rotated_bytes)
                restored_capacity = self.run_remote(
                    "capacity", *common,
                    "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(restored_capacity.returncode, 0)
                lease_report = root / "remote-lease-status.json"
                lease_status = subprocess.run([
                    sys.executable, str(PDR_TOOL), "contract-package",
                    "registry-remote-lease-status", *common,
                    "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN",
                    "--report", str(lease_report),
                ], check=False, capture_output=True, text=True, env=environment)
                self.assertEqual(
                    lease_status.returncode, 0,
                    lease_status.stdout + lease_status.stderr,
                )
                lease_document = json.loads(lease_report.read_bytes())
                self.assertTrue(lease_document["passed"])
                self.assertTrue(lease_document["acceptingCommands"])
                self.assertFalse(lease_document["commandProcessor"]["active"])
                self.assertFalse(lease_document["registryWriter"]["active"])
                control_epoch = (
                    root / "remote-control" / ".command.epoch.json"
                )
                control_epoch_bytes = control_epoch.read_bytes()
                control_epoch.write_text("{}\n", encoding="utf-8")
                corrupt_lease_rejected = self.run_remote(
                    "capacity", *common,
                    "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(corrupt_lease_rejected.returncode, 2)
                self.assertIn(
                    "lease fencing state is invalid",
                    corrupt_lease_rejected.stderr,
                )
                control_epoch.write_bytes(control_epoch_bytes)
                restored_lease = self.run_remote(
                    "lease-status", *common,
                    "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(
                    restored_lease.returncode, 0,
                    restored_lease.stdout + restored_lease.stderr,
                )
                standby_pointer = json.loads(
                    (registry / "registry.json").read_text(encoding="utf-8")
                )
                standby_marker = registry / ".pdr-standby.json"
                standby_marker.write_text(json.dumps({
                    "schemaVersion": 1,
                    "product": "PocoDDSRuntimeTeamContractRegistryStandby",
                    "standbyId": "remote-standby-unit",
                    "registryId": "unit-registry",
                    "sourceRecoveryPointSha256": "d" * 64,
                    "appliedRevision": standby_pointer["revision"],
                    "appliedStateSha256": standby_pointer["stateSha256"],
                    "syncGeneration": 1,
                    "previousMarkerSha256": None,
                    "updatedAt": "2026-08-25T13:10:00Z",
                }, indent=2) + "\n", encoding="utf-8")
                standby_mutation = self.run_remote(
                    "publish", *common, "--request-id", "standby-write-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", str(standby_pointer["revision"]),
                    "--package", str(package), environment=environment,
                )
                self.assertEqual(standby_mutation.returncode, 2)
                self.assertIn("standby is read-only", standby_mutation.stderr)
                self.assertFalse(any(
                    "standby-write-0001" in path.name
                    for path in (root / "remote-control" / "requests").rglob("*.json")
                ))
                standby_marker.unlink()
                drain_state = root / "remote-control" / "drain-state.json"
                drain_state.write_text(json.dumps({
                    "schemaVersion": 1,
                    "product": "PocoDDSRuntimeTeamContractRegistryDrainState",
                    "registryId": "unit-registry", "nodeId": "primary-oslo-01",
                    "handoffId": "remote-handoff-0001", "mode": "draining",
                    "generation": 1, "registryRevision": standby_pointer["revision"],
                    "registryStateSha256": standby_pointer["stateSha256"],
                    "pendingRequestCount": 0,
                    "pendingRequestSetSha256": hashlib.sha256(b"[]").hexdigest(),
                    "observedFencingToken": None, "observedGrantSha256": None,
                    "handoffEvidenceSha256": None, "auditRecordSha256": "e" * 64,
                    "reason": "remote admission fault injection",
                    "updatedAt": "2026-08-25T13:11:00Z",
                }, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
                drained_command = self.run_remote(
                    "publish", *common, "--request-id", "drain-read-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", str(standby_pointer["revision"]),
                    "--package", str(package),
                    environment=environment,
                )
                self.assertEqual(drained_command.returncode, 2)
                self.assertIn("admission is closed", drained_command.stderr)
                self.assertFalse(remote_tool.request_record_path(
                    root / "remote-control", "drain-read-0001"
                ).exists())
                drain_state.unlink()
                audit_records = sorted(
                    (root / "remote-control" / "audit" / "records").glob("*.json")
                )
                tampered_record = json.loads(audit_records[0].read_text(encoding="utf-8"))
                tampered_record["principalId"] = "tampered.actor"
                audit_records[0].write_text(
                    json.dumps(tampered_record, indent=2) + "\n", encoding="utf-8"
                )
                tampered_audit = self.run_remote(
                    "audit-checkpoint-verify", "--control-directory",
                    str(root / "remote-control"), "--registry-id", "unit-registry",
                    "--audit-archive-directory", str(archive_directory),
                    "--checkpoint", str(checkpoint),
                    "--audit-policy", str(audit_policy),
                    "--expected-audit-policy-id", "registry-unit-remote-auditors",
                    "--expected-audit-policy-sha256", audit_policy_sha,
                    "--verification-time", "2026-08-25T13:01:00Z",
                    environment=environment,
                )
                self.assertEqual(tampered_audit.returncode, 2)
                self.assertIn("filename or sequence changed", tampered_audit.stderr)
            finally:
                server.terminate()
                try:
                    server.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
