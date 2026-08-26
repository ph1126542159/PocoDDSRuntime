#!/usr/bin/env python3

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
LEADER_TOOL = TOOLS / "team_contract_registry_leader.py"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_team_contract_registry as registry_test  # noqa: E402
import team_contract_registry_handoff as handoff_tool  # noqa: E402


class TeamContractRegistryLeaderTests(unittest.TestCase):
    @staticmethod
    def invoke(*arguments: str,
               environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(LEADER_TOOL), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    @staticmethod
    def leader_fixture(root: Path) -> tuple[Path, str, dict[str, str]]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        trust = root / "leader-trust"
        keys = trust / "keys"
        keys.mkdir(parents=True)
        private = trust / "leader.private.pem"
        public = keys / "authority.pem"
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
        policy = trust / "policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRegistryLeaderTrustPolicy",
            "policyId": "registry-leader-authorities",
            "allowedSigners": [{
                "keyId": "oslo-leader-authority-2026",
                "algorithm": "Ed25519",
                "publicKey": "keys/authority.pem",
                "publicKeySha256": hashlib.sha256(public.read_bytes()).hexdigest(),
                "authorityIds": ["registry-leader-authority"],
                "registryIds": ["unit-registry"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": [],
        }, indent=2) + "\n", encoding="utf-8")
        environment = dict(
            os.environ, PDR_TEST_LEADER_KEY=str(private)
        )
        return policy, hashlib.sha256(policy.read_bytes()).hexdigest(), environment

    @staticmethod
    def handoff_fixture(root: Path, now: datetime, pointer: dict[str, object],
                        fence_token: int, fence_sha: str) \
            -> tuple[Path, Path, str]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        trust = root / "handoff-trust"
        keys = trust / "keys"
        keys.mkdir(parents=True)
        public = keys / "primary-oslo-01.pem"
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(65, 97)))
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
                "publicKey": "keys/primary-oslo-01.pem",
                "publicKeySha256": hashlib.sha256(public.read_bytes()).hexdigest(),
                "registryIds": ["unit-registry"],
                "nodeIds": ["primary-oslo-01"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": "2030-01-01T00:00:00Z",
            }],
            "revokedKeys": [],
        }, indent=2) + "\n", encoding="utf-8")
        evidence = {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRegistryHandoffEvidence",
            "handoffId": "handoff-oslo-0001", "registryId": "unit-registry",
            "nodeId": "primary-oslo-01", "drainGeneration": 1,
            "registryRevision": pointer["revision"],
            "registryStateSha256": pointer["stateSha256"],
            "observedFencingToken": fence_token,
            "observedGrantSha256": fence_sha, "pendingRequestCount": 0,
            "pendingRequestSetSha256": handoff_tool.EMPTY_PENDING_SHA256,
            "auditSequence": 0, "auditHeadSha256": "d" * 64,
            "issuedAt": (now - timedelta(seconds=30)).isoformat(),
            "expiresAt": (now + timedelta(minutes=30)).isoformat(),
            "signer": {
                "keyId": "primary-oslo-handoff-2026", "algorithm": "Ed25519"
            },
        }
        evidence["signer"]["signature"] = __import__("base64").b64encode(
            key.sign(json.dumps(
                evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8"))
        ).decode("ascii")
        evidence_path = root / "handoff-evidence.json"
        evidence_path.write_text(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return evidence_path, policy, hashlib.sha256(policy.read_bytes()).hexdigest()

    def test_external_grants_fence_old_primary_and_promote_exact_standby(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = registry_test.TeamContractRegistryTests()
            source, package_policy, package_policy_sha, package_environment = \
                helper.initialized(root)
            package1 = helper.create_package(
                root, "1.0.0", "1.0.0", package_environment
            )
            self.assertEqual(
                helper.publish(
                    source, package_policy, package_policy_sha, package1
                ).returncode,
                0,
            )
            standby = root / "standby"
            shutil.copytree(source, standby)
            source_pointer = json.loads((source / "registry.json").read_bytes())
            (standby / ".pdr-standby.json").write_text(json.dumps({
                "schemaVersion": 1,
                "product": "PocoDDSRuntimeTeamContractRegistryStandby",
                "standbyId": "standby-oslo-01",
                "registryId": "unit-registry",
                "sourceRecoveryPointSha256": "a" * 64,
                "appliedRevision": source_pointer["revision"],
                "appliedStateSha256": source_pointer["stateSha256"],
                "syncGeneration": 1,
                "previousMarkerSha256": None,
                "updatedAt": "2026-08-25T12:10:00Z",
            }, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

            leader_policy, leader_policy_sha, leader_environment = \
                self.leader_fixture(root)
            authority = root / "external-leader-authority"
            audit = root / "leader-operations.jsonl"
            now = datetime.now(timezone.utc)
            issued = (now - timedelta(minutes=2)).isoformat()
            not_before = (now - timedelta(minutes=1)).isoformat()
            expires = (now + timedelta(hours=1)).isoformat()
            leader_trust = [
                "--leader-trust-policy", str(leader_policy),
                "--expected-leader-trust-policy-id",
                "registry-leader-authorities",
                "--expected-leader-trust-policy-sha256", leader_policy_sha,
            ]

            def issue(purpose: str, leader_id: str | None, token: int,
                      previous_sha: str, pointer: dict[str, object],
                      handoff: tuple[Path, Path, str] | None = None) \
                    -> subprocess.CompletedProcess[str]:
                arguments = [
                    "issue", "--authority", str(authority),
                    "--authority-id", "registry-leader-authority",
                    "--registry-id", "unit-registry", "--purpose", purpose,
                    "--expected-current-token", str(token),
                    "--expected-current-grant-sha256", previous_sha,
                    "--baseline-revision", str(pointer["revision"]),
                    "--baseline-state-sha256", str(pointer["stateSha256"]),
                    "--issued-at", issued, "--not-before", not_before,
                    "--expires-at", expires,
                    "--key-id", "oslo-leader-authority-2026",
                    "--private-key-environment", "PDR_TEST_LEADER_KEY",
                    "--operator", "ha.operator", "--operation-audit", str(audit),
                    *leader_trust,
                ]
                if leader_id is not None:
                    arguments.extend(["--leader-id", leader_id])
                if handoff is not None:
                    arguments.extend([
                        "--handoff-evidence", str(handoff[0]),
                        "--handoff-trust-policy", str(handoff[1]),
                        "--expected-handoff-trust-policy-id",
                        "registry-handoff-nodes",
                        "--expected-handoff-trust-policy-sha256", handoff[2],
                        "--handoff-verification-time", now.isoformat(),
                    ])
                return self.invoke(*arguments, environment=leader_environment)

            initial = issue("leadership", "primary-oslo-01", 0, "0" * 64,
                            source_pointer)
            self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
            current = authority / "current-grant.json"
            grant1_sha = hashlib.sha256(current.read_bytes()).hexdigest()
            activation_common = [
                "--trust-policy", str(package_policy),
                "--expected-trust-policy-id", "registry-unit-policy",
                "--expected-trust-policy-sha256", package_policy_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
                "--leader-verification-time", now.isoformat(),
                *leader_trust,
            ]
            enrolled = self.invoke(
                "activate", "--registry", str(source),
                "--node-id", "primary-oslo-01", "--current-grant", str(current),
                "--expected-current-grant-sha256", grant1_sha,
                "--operator", "ha.operator", "--operation-audit", str(audit),
                "--confirm-enroll-primary", *activation_common,
            )
            self.assertEqual(enrolled.returncode, 0, enrolled.stdout + enrolled.stderr)

            package2 = helper.create_package(
                root, "1.1.0", "1.1.0", package_environment
            )
            accepted = helper.publish(
                source, package_policy, package_policy_sha, package2
            )
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            source_pointer = json.loads((source / "registry.json").read_bytes())

            unsafe_transfer = issue(
                "leadership", "standby-oslo-01", 1, grant1_sha, source_pointer
            )
            self.assertEqual(unsafe_transfer.returncode, 2)
            self.assertIn("intervening fence", unsafe_transfer.stderr)
            self.assertEqual(hashlib.sha256(current.read_bytes()).hexdigest(), grant1_sha)

            fenced = issue("fence", None, 1, grant1_sha, source_pointer)
            self.assertEqual(fenced.returncode, 0, fenced.stdout + fenced.stderr)
            grant2_sha = hashlib.sha256(current.read_bytes()).hexdigest()
            revision_before = source_pointer["revision"]
            package3 = helper.create_package(
                root, "1.2.0", "1.2.0", package_environment
            )
            old_rejected = helper.publish(
                source, package_policy, package_policy_sha, package3
            )
            self.assertEqual(old_rejected.returncode, 2)
            self.assertIn("fencing token is stale", old_rejected.stderr)
            self.assertEqual(
                json.loads((source / "registry.json").read_bytes())["revision"],
                revision_before,
            )

            shutil.rmtree(standby)
            shutil.copytree(source, standby)
            (standby / ".pdr-leader.json").unlink()
            (standby / ".pdr-standby.json").write_text(json.dumps({
                "schemaVersion": 1,
                "product": "PocoDDSRuntimeTeamContractRegistryStandby",
                "standbyId": "standby-oslo-01",
                "registryId": "unit-registry",
                "sourceRecoveryPointSha256": "b" * 64,
                "appliedRevision": source_pointer["revision"],
                "appliedStateSha256": source_pointer["stateSha256"],
                "syncGeneration": 2,
                "previousMarkerSha256": "c" * 64,
                "updatedAt": "2026-08-25T12:20:00Z",
            }, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

            missing_handoff = issue(
                "leadership", "standby-oslo-01", 2, grant2_sha, source_pointer
            )
            self.assertEqual(missing_handoff.returncode, 2)
            self.assertIn("signed handoff evidence", missing_handoff.stderr)
            handoff = self.handoff_fixture(
                root, now, source_pointer, 2, grant2_sha
            )
            promoted_grant = issue(
                "leadership", "standby-oslo-01", 2, grant2_sha,
                source_pointer, handoff,
            )
            self.assertEqual(
                promoted_grant.returncode, 0,
                promoted_grant.stdout + promoted_grant.stderr,
            )
            grant3_bytes = current.read_bytes()
            grant3_sha = hashlib.sha256(grant3_bytes).hexdigest()
            promoted = self.invoke(
                "activate", "--registry", str(standby),
                "--node-id", "standby-oslo-01", "--current-grant", str(current),
                "--expected-current-grant-sha256", grant3_sha,
                "--operator", "ha.operator", "--operation-audit", str(audit),
                *activation_common,
            )
            self.assertEqual(promoted.returncode, 0, promoted.stdout + promoted.stderr)
            self.assertFalse((standby / ".pdr-standby.json").exists())
            self.assertEqual(
                json.loads((standby / ".pdr-leader.json").read_bytes())["fencingToken"],
                3,
            )
            new_accepted = helper.publish(
                standby, package_policy, package_policy_sha, package3
            )
            self.assertEqual(
                new_accepted.returncode, 0, new_accepted.stdout + new_accepted.stderr
            )
            still_fenced = helper.publish(
                source, package_policy, package_policy_sha,
                helper.create_package(
                    root, "1.3.0", "1.3.0", package_environment
                ),
            )
            self.assertEqual(still_fenced.returncode, 2)

            token1 = next((authority / "grants").glob(f"{1:020d}-*.json"))
            current.write_bytes(token1.read_bytes())
            rollback_rejected = helper.publish(
                standby, package_policy, package_policy_sha,
                helper.create_package(
                    root, "1.4.0", "1.4.0", package_environment
                ),
            )
            self.assertEqual(rollback_rejected.returncode, 2)
            self.assertIn("authority rollback detected", rollback_rejected.stderr)
            old_rollback_rejected = helper.publish(
                source, package_policy, package_policy_sha,
                helper.create_package(
                    root, "1.5.0", "1.5.0", package_environment
                ),
            )
            self.assertEqual(old_rollback_rejected.returncode, 2)
            self.assertIn("authority rollback detected", old_rollback_rejected.stderr)
            current.write_bytes(grant3_bytes)

            status = self.invoke(
                "status", "--registry", str(standby),
                "--verification-time", now.isoformat(),
            )
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
            expired = self.invoke(
                "status", "--registry", str(standby),
                "--verification-time", (now + timedelta(hours=2)).isoformat(),
            )
            self.assertEqual(expired.returncode, 2)
            self.assertIn("not currently active", expired.stderr)
            self.assertEqual(len(audit.read_text(encoding="utf-8").splitlines()), 5)
            print(
                "PDR_REGISTRY_LEADER_PASS enroll=1 fence=1 transferGap=1 "
                "promote=1 oldWriter=1 rollback=1 expiry=1 history=1 handoff=1"
            )


if __name__ == "__main__":
    unittest.main()
