#!/usr/bin/env python3

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
LEADER_TOOL = TOOLS / "team_contract_registry_leader.py"
REMOTE_TOOL = TOOLS / "team_contract_registry_remote.py"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import team_contract_registry_remote as remote_tool  # noqa: E402
import test_team_contract_registry as registry_test  # noqa: E402
import test_team_contract_registry_handoff as handoff_test  # noqa: E402
import test_team_contract_registry_leader as leader_test  # noqa: E402
import test_team_contract_registry_remote as remote_test  # noqa: E402


class TeamContractRegistryRemoteDrainTests(unittest.TestCase):
    @staticmethod
    def invoke(tool: Path, *arguments: str,
               environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(tool), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    @staticmethod
    def port() -> int:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def test_operator_remote_drain_is_path_free_replayable_and_fence_gated(self):
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

            def issue(purpose: str, token: int, previous_sha: str) \
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
                if purpose == "leadership":
                    arguments.extend(["--leader-id", "primary-oslo-01"])
                return self.invoke(LEADER_TOOL, *arguments, environment=leader_environment)

            first = issue("leadership", 0, "0" * 64)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            grant1_sha = hashlib.sha256(current.read_bytes()).hexdigest()
            activation = self.invoke(
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
            self.assertEqual(activation.returncode, 0, activation.stdout + activation.stderr)

            access_policy, access_sha, access_environment = \
                remote_test.TeamContractRegistryRemoteTests.access_policy(root)
            _, _, handoff_environment = \
                handoff_test.TeamContractRegistryHandoffTests.handoff_signer(root)
            environment = dict(os.environ)
            environment.update(leader_environment)
            environment.update(access_environment)
            environment.update(handoff_environment)
            control = root / "remote-control"
            evidence_directory = root / "external-handoff-evidence"
            port = self.port()
            server = subprocess.Popen([
                sys.executable, str(REMOTE_TOOL), "serve",
                "--registry", str(registry), "--bind", "127.0.0.1",
                "--port", str(port), "--allow-insecure-loopback", "--quiet",
                "--control-directory", str(control),
                "--access-policy", str(access_policy),
                "--expected-access-policy-id", "registry-unit-remote-access",
                "--expected-access-policy-sha256", access_sha,
                "--trust-policy", str(package_policy),
                "--expected-trust-policy-id", "registry-unit-policy",
                "--expected-trust-policy-sha256", package_policy_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
                "--node-id", "primary-oslo-01",
                "--handoff-evidence-directory", str(evidence_directory),
                "--handoff-key-id", "primary-oslo-handoff-2026",
                "--handoff-private-key-environment", "PDR_TEST_HANDOFF_KEY",
                "--handoff-leader-verification-time", now.isoformat(),
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
               env=environment)
            try:
                remote_test.TeamContractRegistryRemoteTests.wait_server(server, port)
                query = [
                    "--url", f"http://127.0.0.1:{port}",
                    "--registry-id", "unit-registry", "--allow-insecure-loopback",
                ]
                drain = [
                    *query, "--handoff-id", "remote-handoff-0001",
                    "--expected-generation", "0", "--expected-revision",
                    str(pointer["revision"]), "--expected-state-sha256",
                    pointer["stateSha256"],
                ]
                denied = self.invoke(
                    REMOTE_TOOL, "drain-start", *drain,
                    "--token-environment", "PDR_TEST_REMOTE_AUDITOR_TOKEN",
                    "--reason", "unauthorized drain", environment=environment,
                )
                self.assertEqual(denied.returncode, 2)
                self.assertIn("operator role", denied.stderr)
                started = self.invoke(
                    REMOTE_TOOL, "drain-start", *drain,
                    "--token-environment", "PDR_TEST_REMOTE_OPERATOR_TOKEN",
                    "--reason", "planned remote failover", environment=environment,
                )
                self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
                replay = self.invoke(
                    REMOTE_TOOL, "drain-start", *drain,
                    "--token-environment", "PDR_TEST_REMOTE_OPERATOR_TOKEN",
                    "--reason", "planned remote failover", environment=environment,
                )
                self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
                self.assertIn("replayed=true", replay.stdout)
                mismatched_start = self.invoke(
                    REMOTE_TOOL, "drain-start", *drain,
                    "--token-environment", "PDR_TEST_REMOTE_OPERATOR_TOKEN",
                    "--reason", "different retry payload", environment=environment,
                )
                self.assertEqual(mismatched_start.returncode, 2)
                self.assertIn("does not match persisted start", mismatched_start.stderr)
                status = self.invoke(
                    REMOTE_TOOL, "drain-status", *query,
                    "--token-environment", "PDR_TEST_REMOTE_OPERATOR_TOKEN",
                    environment=environment,
                )
                self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
                self.assertIn("mode=draining", status.stdout)
                blocked = self.invoke(
                    REMOTE_TOOL, "publish", *query,
                    "--request-id", "remote-drain-write-0001",
                    "--token-environment", "PDR_TEST_REMOTE_PUBLISHER_TOKEN",
                    "--expected-revision", str(pointer["revision"]),
                    "--package", str(package), environment=environment,
                )
                self.assertEqual(blocked.returncode, 2)
                self.assertIn("admission is closed", blocked.stderr)
                self.assertFalse(remote_tool.request_record_path(
                    control, "remote-drain-write-0001"
                ).exists())

                final_common = [
                    *query, "--handoff-id", "remote-handoff-0001",
                    "--expected-generation", "1", "--expected-revision",
                    str(pointer["revision"]), "--expected-state-sha256",
                    pointer["stateSha256"],
                    "--token-environment", "PDR_TEST_REMOTE_OPERATOR_TOKEN",
                    "--issued-at", now.isoformat(),
                    "--expires-at", (now + timedelta(minutes=30)).isoformat(),
                ]
                early = self.invoke(
                    REMOTE_TOOL, "drain-finalize", *final_common,
                    "--evidence-output", str(root / "early-evidence.json"),
                    environment=environment,
                )
                self.assertEqual(early.returncode, 2)
                self.assertIn("newer active fence", early.stderr)
                fence = issue("fence", 1, grant1_sha)
                self.assertEqual(fence.returncode, 0, fence.stdout + fence.stderr)
                evidence1 = root / "downloaded-handoff-1.json"
                finalized = self.invoke(
                    REMOTE_TOOL, "drain-finalize", *final_common,
                    "--evidence-output", str(evidence1), environment=environment,
                )
                self.assertEqual(
                    finalized.returncode, 0, finalized.stdout + finalized.stderr
                )
                evidence2 = root / "downloaded-handoff-2.json"
                finalized_replay = self.invoke(
                    REMOTE_TOOL, "drain-finalize", *final_common,
                    "--evidence-output", str(evidence2), environment=environment,
                )
                self.assertEqual(finalized_replay.returncode, 0)
                self.assertIn("replayed=true", finalized_replay.stdout)
                self.assertEqual(evidence1.read_bytes(), evidence2.read_bytes())
                persisted = next(evidence_directory.glob("*.json"))
                self.assertEqual(evidence1.read_bytes(), persisted.read_bytes())
                mismatched_finalize = self.invoke(
                    REMOTE_TOOL, "drain-finalize",
                    *final_common[:-2],
                    "--expires-at", (now + timedelta(minutes=25)).isoformat(),
                    "--evidence-output", str(root / "mismatched-evidence.json"),
                    environment=environment,
                )
                self.assertEqual(mismatched_finalize.returncode, 2)
                self.assertIn(
                    "does not match persisted finalize", mismatched_finalize.stderr
                )
                self.assertFalse((root / "mismatched-evidence.json").exists())
                resumed = self.invoke(
                    REMOTE_TOOL, "drain-resume", *query,
                    "--handoff-id", "remote-handoff-0001",
                    "--expected-generation", "1", "--expected-revision",
                    str(pointer["revision"]), "--expected-state-sha256",
                    pointer["stateSha256"],
                    "--token-environment", "PDR_TEST_REMOTE_OPERATOR_TOKEN",
                    "--reason", "unsafe old leader resume", environment=environment,
                )
                self.assertEqual(resumed.returncode, 2)
                self.assertIn("fencing token is stale", resumed.stderr)
                print(
                    "PDR_REGISTRY_REMOTE_DRAIN_PASS rbac=1 pathFree=1 replay=1 "
                    "admission=1 fence=1 evidence=1 resume=1"
                )
            finally:
                server.terminate()
                try:
                    server.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
