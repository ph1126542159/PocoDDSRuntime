#!/usr/bin/env python3

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
LEADER_TOOL = TOOLS / "team_contract_registry_leader.py"
HANDOFF_TOOL = TOOLS / "team_contract_registry_handoff.py"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import team_contract_registry_handoff as handoff_tool  # noqa: E402
import team_contract_registry_remote as remote_tool  # noqa: E402
import test_team_contract_registry as registry_test  # noqa: E402
import test_team_contract_registry_leader as leader_test  # noqa: E402


class TeamContractRegistryHandoffTests(unittest.TestCase):
    @staticmethod
    def invoke(tool: Path, *arguments: str,
               environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(tool), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    @staticmethod
    def handoff_signer(root: Path) -> tuple[Path, str, dict[str, str]]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        trust = root / "handoff-trust"
        keys = trust / "keys"
        keys.mkdir(parents=True)
        private = trust / "primary.private.pem"
        public = keys / "primary.pem"
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(65, 97)))
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
            "product": "PocoDDSRuntimeTeamContractRegistryHandoffTrustPolicy",
            "policyId": "registry-handoff-nodes",
            "allowedSigners": [{
                "keyId": "primary-oslo-handoff-2026", "algorithm": "Ed25519",
                "publicKey": "keys/primary.pem",
                "publicKeySha256": hashlib.sha256(public.read_bytes()).hexdigest(),
                "registryIds": ["unit-registry"], "nodeIds": ["primary-oslo-01"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": [],
        }, indent=2) + "\n", encoding="utf-8")
        return (
            policy, hashlib.sha256(policy.read_bytes()).hexdigest(),
            dict(os.environ, PDR_TEST_HANDOFF_KEY=str(private)),
        )

    def test_drain_closes_admission_and_signed_handoff_gates_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = registry_test.TeamContractRegistryTests()
            registry, package_policy, package_policy_sha, package_environment = \
                helper.initialized(root)
            package = helper.create_package(root, "1.0.0", "1.0.0", package_environment)
            self.assertEqual(
                helper.publish(
                    registry, package_policy, package_policy_sha, package
                ).returncode,
                0,
            )
            pointer = json.loads((registry / "registry.json").read_bytes())
            leader_policy, leader_policy_sha, leader_environment = \
                leader_test.TeamContractRegistryLeaderTests.leader_fixture(root)
            authority = root / "leader-authority"
            current = authority / "current-grant.json"
            now = datetime.now(timezone.utc)
            issued = (now - timedelta(minutes=2)).isoformat()
            not_before = (now - timedelta(minutes=1)).isoformat()
            expires = (now + timedelta(hours=1)).isoformat()
            leader_trust = [
                "--leader-trust-policy", str(leader_policy),
                "--expected-leader-trust-policy-id", "registry-leader-authorities",
                "--expected-leader-trust-policy-sha256", leader_policy_sha,
            ]

            def issue(purpose: str, leader_id: str | None, token: int,
                      previous_sha: str, handoff: tuple[Path, Path, str] | None = None) \
                    -> subprocess.CompletedProcess[str]:
                arguments = [
                    "issue", "--authority", str(authority),
                    "--authority-id", "registry-leader-authority",
                    "--registry-id", "unit-registry", "--purpose", purpose,
                    "--expected-current-token", str(token),
                    "--expected-current-grant-sha256", previous_sha,
                    "--baseline-revision", str(pointer["revision"]),
                    "--baseline-state-sha256", pointer["stateSha256"],
                    "--issued-at", issued, "--not-before", not_before,
                    "--expires-at", expires,
                    "--key-id", "oslo-leader-authority-2026",
                    "--private-key-environment", "PDR_TEST_LEADER_KEY",
                    "--operator", "ha.operator", *leader_trust,
                ]
                if leader_id is not None:
                    arguments.extend(["--leader-id", leader_id])
                if handoff:
                    arguments.extend([
                        "--handoff-evidence", str(handoff[0]),
                        "--handoff-trust-policy", str(handoff[1]),
                        "--expected-handoff-trust-policy-id", "registry-handoff-nodes",
                        "--expected-handoff-trust-policy-sha256", handoff[2],
                        "--handoff-verification-time", now.isoformat(),
                    ])
                return self.invoke(LEADER_TOOL, *arguments, environment=leader_environment)

            grant1 = issue("leadership", "primary-oslo-01", 0, "0" * 64)
            self.assertEqual(grant1.returncode, 0, grant1.stdout + grant1.stderr)
            grant1_sha = hashlib.sha256(current.read_bytes()).hexdigest()
            activated = self.invoke(
                LEADER_TOOL, "activate", "--registry", str(registry),
                "--node-id", "primary-oslo-01", "--current-grant", str(current),
                "--expected-current-grant-sha256", grant1_sha,
                "--operator", "ha.operator",
                "--operation-audit", str(root / "leader-audit.jsonl"),
                "--confirm-enroll-primary", "--trust-policy", str(package_policy),
                "--expected-trust-policy-id", "registry-unit-policy",
                "--expected-trust-policy-sha256", package_policy_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
                "--leader-verification-time", now.isoformat(), *leader_trust,
            )
            self.assertEqual(activated.returncode, 0, activated.stdout + activated.stderr)

            control = root / "remote-control"
            common = [
                "--registry", str(registry), "--control-directory", str(control),
                "--registry-id", "unit-registry", "--node-id", "primary-oslo-01",
                "--handoff-id", "handoff-oslo-0001", "--expected-revision",
                str(pointer["revision"]), "--expected-state-sha256",
                pointer["stateSha256"], "--operator", "ha.operator",
            ]
            started = self.invoke(
                HANDOFF_TOOL, "start", *common, "--expected-generation", "0",
                "--reason", "planned failover",
            )
            self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
            with self.assertRaisesRegex(ValueError, "admission is closed"):
                handoff_tool.require_command_admission(control, "unit-registry")

            pending_id = "handoff-pending-0001"
            pending_path = remote_tool.request_record_path(control, pending_id)
            remote_tool.registry_tool.exclusive_bytes(
                pending_path, remote_tool.package_tool.json_bytes({
                    "schemaVersion": 1, "requestId": pending_id,
                    "requestSha256": "a" * 64, "principalId": "handoff.reader",
                    "operation": "verify", "startedRevision": pointer["revision"],
                    "status": "pending",
                }),
            )
            handoff_policy, handoff_policy_sha, handoff_environment = \
                self.handoff_signer(root)
            evidence = root / "handoff-evidence.json"
            finalize = [
                "finalize", *common, "--expected-generation", "1",
                "--leader-verification-time", now.isoformat(),
                "--issued-at", now.isoformat(),
                "--expires-at", (now + timedelta(minutes=30)).isoformat(),
                "--key-id", "primary-oslo-handoff-2026",
                "--private-key-environment", "PDR_TEST_HANDOFF_KEY",
                "--output", str(evidence),
            ]
            pending_rejected = self.invoke(
                HANDOFF_TOOL, *finalize, environment=handoff_environment
            )
            self.assertEqual(pending_rejected.returncode, 2)
            self.assertIn("pending requests", pending_rejected.stderr)
            pending_path.unlink()
            no_fence = self.invoke(
                HANDOFF_TOOL, *finalize, environment=handoff_environment
            )
            self.assertEqual(no_fence.returncode, 2)
            self.assertIn("newer active fence", no_fence.stderr)

            grant2 = issue("fence", None, 1, grant1_sha)
            self.assertEqual(grant2.returncode, 0, grant2.stdout + grant2.stderr)
            grant2_sha = hashlib.sha256(current.read_bytes()).hexdigest()
            finalized = self.invoke(
                HANDOFF_TOOL, *finalize, environment=handoff_environment
            )
            self.assertEqual(finalized.returncode, 0, finalized.stdout + finalized.stderr)
            state = json.loads((control / "drain-state.json").read_bytes())
            self.assertEqual(state["mode"], "drained")
            self.assertEqual(state["observedFencingToken"], 2)
            verified, evidence_sha = handoff_tool.load_and_verify_evidence(
                evidence, handoff_policy, "registry-handoff-nodes",
                handoff_policy_sha, now.isoformat(),
            )
            self.assertEqual(verified["observedGrantSha256"], grant2_sha)
            self.assertEqual(state["handoffEvidenceSha256"], evidence_sha)

            tampered = root / "handoff-tampered.json"
            changed = json.loads(evidence.read_bytes())
            changed["registryRevision"] += 1
            tampered.write_text(json.dumps(changed) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "verification failed"):
                handoff_tool.load_and_verify_evidence(
                    tampered, handoff_policy, "registry-handoff-nodes",
                    handoff_policy_sha, now.isoformat(),
                )

            missing = issue("leadership", "standby-oslo-01", 2, grant2_sha)
            self.assertEqual(missing.returncode, 2)
            accepted = issue(
                "leadership", "standby-oslo-01", 2, grant2_sha,
                (evidence, handoff_policy, handoff_policy_sha),
            )
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            resume = self.invoke(
                HANDOFF_TOOL, "resume", *common, "--expected-generation", "1",
                "--reason", "unsafe resume attempt",
            )
            self.assertEqual(resume.returncode, 2)
            self.assertIn("fencing token is stale", resume.stderr)
            print(
                "PDR_REGISTRY_HANDOFF_PASS drain=1 admission=1 pending=1 "
                "fence=1 evidence=1 tamper=1 leaderGate=1 resume=1"
            )


if __name__ == "__main__":
    unittest.main()
