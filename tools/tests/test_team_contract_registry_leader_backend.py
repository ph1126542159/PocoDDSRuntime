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
REGISTRY_TOOL = TOOLS / "team_contract_registry.py"
PDR_TOOL = TOOLS / "pdr.py"
ADAPTER = Path(__file__).resolve().parent / "fixtures/leader_backend_adapter.py"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_team_contract_registry as registry_test  # noqa: E402
import test_team_contract_registry_leader as leader_test  # noqa: E402


class TeamContractRegistryLeaderBackendTests(unittest.TestCase):
    @staticmethod
    def invoke(tool: Path, *arguments: str,
               environment: dict[str, str] | None = None) \
            -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(tool), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    def test_external_backend_is_pinned_cas_fenced_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = registry_test.TeamContractRegistryTests()
            registry, package_policy, package_policy_sha, package_environment = \
                helper.initialized(root)
            package1 = helper.create_package(
                root, "1.0.0", "1.0.0", package_environment
            )
            self.assertEqual(
                helper.publish(
                    registry, package_policy, package_policy_sha, package1
                ).returncode,
                0,
            )
            package2 = helper.create_package(
                root, "1.0.1", "1.0.1", package_environment
            )
            pointer = json.loads((registry / "registry.json").read_bytes())
            leader_policy, leader_policy_sha, leader_environment = \
                leader_test.TeamContractRegistryLeaderTests.leader_fixture(root)
            backend_root = root / "linearizable-authority-store"
            environment = dict(leader_environment)
            environment.update({
                "PDR_TEST_LEADER_BACKEND_ROOT": str(backend_root),
                "PDR_TEST_LEADER_BACKEND_MODE": "normal",
            })
            adapter = root / "leader_backend_adapter.py"
            adapter.write_bytes(ADAPTER.read_bytes())
            config = root / "leader-backend.json"
            executable = Path(sys.executable).resolve()
            config_document = {
                "schemaVersion": 1,
                "product": "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig",
                "backendId": "unit-linearizable-backend",
                "kind": "external-command",
                "authorityIds": ["registry-leader-authority"],
                "registryIds": ["unit-registry"],
                "executable": str(executable),
                "executableSha256": hashlib.sha256(
                    executable.read_bytes()
                ).hexdigest(),
                "arguments": [str(adapter)],
                "artifactPins": [{
                    "path": str(adapter),
                    "sha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
                }],
                "environmentVariables": [
                    "PDR_TEST_LEADER_BACKEND_ROOT",
                    "PDR_TEST_LEADER_BACKEND_MODE",
                ],
                "timeoutSeconds": 1,
                "maxResponseBytes": 65536,
            }
            config.write_text(
                json.dumps(config_document, indent=2) + "\n", encoding="utf-8"
            )
            config_bytes = config.read_bytes()
            config_sha = hashlib.sha256(config_bytes).hexdigest()
            now = datetime.now(timezone.utc)
            issued = (now - timedelta(minutes=2)).isoformat()
            not_before = (now - timedelta(minutes=1)).isoformat()
            expires = (now + timedelta(hours=1)).isoformat()
            backend_args = [
                "--authority-backend-config", str(config),
                "--expected-authority-backend-config-sha256", config_sha,
            ]
            leader_trust = [
                "--leader-trust-policy", str(leader_policy),
                "--expected-leader-trust-policy-id",
                "registry-leader-authorities",
                "--expected-leader-trust-policy-sha256", leader_policy_sha,
            ]

            unsafe_config = root / "unsafe-leader-backend.json"
            unsafe_document = dict(config_document)
            unsafe_document["environmentVariables"] = [
                *config_document["environmentVariables"], "PDR_TEST_LEADER_KEY"
            ]
            unsafe_config.write_text(
                json.dumps(unsafe_document, indent=2) + "\n", encoding="utf-8"
            )
            unsafe_sha = hashlib.sha256(unsafe_config.read_bytes()).hexdigest()
            unsafe = self.invoke(
                LEADER_TOOL, "issue", "--authority-backend-config",
                str(unsafe_config),
                "--expected-authority-backend-config-sha256", unsafe_sha,
                "--authority-id", "registry-leader-authority",
                "--registry-id", "unit-registry", "--purpose", "leadership",
                "--leader-id", "primary-oslo-01",
                "--expected-current-token", "0",
                "--expected-current-grant-sha256", "0" * 64,
                "--baseline-revision", str(pointer["revision"]),
                "--baseline-state-sha256", pointer["stateSha256"],
                "--issued-at", issued, "--not-before", not_before,
                "--expires-at", expires,
                "--key-id", "oslo-leader-authority-2026",
                "--private-key-environment", "PDR_TEST_LEADER_KEY",
                "--operator", "ha.operator", *leader_trust,
                environment=environment,
            )
            self.assertEqual(unsafe.returncode, 2)
            self.assertIn("must not receive signing key", unsafe.stderr)

            def issue(purpose: str, token: int, previous_sha: str) \
                    -> subprocess.CompletedProcess[str]:
                arguments = [
                    "issue", *backend_args,
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
                return self.invoke(LEADER_TOOL, *arguments, environment=environment)

            first = issue("leadership", 0, "0" * 64)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            grant1_sha = first.stdout.strip().rsplit("sha256=", 1)[1]
            activation = self.invoke(
                LEADER_TOOL, "activate", "--registry", str(registry),
                "--node-id", "primary-oslo-01", *backend_args,
                "--authority-id", "registry-leader-authority",
                "--expected-current-grant-sha256", grant1_sha,
                "--operator", "ha.operator", "--operation-audit",
                str(root / "leader-audit.jsonl"), "--confirm-enroll-primary",
                "--trust-policy", str(package_policy),
                "--expected-trust-policy-id", "registry-unit-policy",
                "--expected-trust-policy-sha256", package_policy_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
                "--leader-verification-time", now.isoformat(), *leader_trust,
                environment=environment,
            )
            self.assertEqual(
                activation.returncode, 0, activation.stdout + activation.stderr
            )
            binding = json.loads((registry / ".pdr-leader.json").read_bytes())
            self.assertEqual(binding["schemaVersion"], 2)
            self.assertIsNone(binding["grantPath"])
            self.assertEqual(
                binding["authorityBackend"]["configSha256"], config_sha
            )

            def publish() -> subprocess.CompletedProcess[str]:
                return self.invoke(
                    REGISTRY_TOOL, "publish",
                    *helper.common(registry, package_policy, package_policy_sha),
                    "--package", str(package2), "--actor", "publisher",
                    "--occurred-at", "2026-08-25T12:20:00Z",
                    environment=environment,
                )

            environment["PDR_TEST_LEADER_BACKEND_MODE"] = "timeout"
            timeout = publish()
            self.assertEqual(timeout.returncode, 2, timeout.stdout + timeout.stderr)
            self.assertIn("backend timed out", timeout.stderr)
            environment["PDR_TEST_LEADER_BACKEND_MODE"] = "mismatch"
            mismatch = publish()
            self.assertEqual(mismatch.returncode, 2, mismatch.stdout + mismatch.stderr)
            self.assertIn("malformed or mismatched", mismatch.stderr)
            environment["PDR_TEST_LEADER_BACKEND_MODE"] = "normal"

            config.write_bytes(config_bytes + b" ")
            config_drift = publish()
            self.assertEqual(
                config_drift.returncode, 2,
                config_drift.stdout + config_drift.stderr,
            )
            self.assertIn("configuration identity is not pinned", config_drift.stderr)
            config.write_bytes(config_bytes)
            adapter_bytes = adapter.read_bytes()
            try:
                adapter.write_bytes(adapter_bytes + b"\n")
                adapter_drift = publish()
                self.assertEqual(
                    adapter_drift.returncode, 2,
                    adapter_drift.stdout + adapter_drift.stderr,
                )
                self.assertIn("backend artifact digest changed", adapter_drift.stderr)
            finally:
                adapter.write_bytes(adapter_bytes)

            fence_arguments = [
                "issue", *backend_args,
                "--authority-id", "registry-leader-authority",
                "--registry-id", "unit-registry", "--purpose", "fence",
                "--expected-current-token", "1",
                "--expected-current-grant-sha256", grant1_sha,
                "--baseline-revision", str(pointer["revision"]),
                "--baseline-state-sha256", pointer["stateSha256"],
                "--issued-at", issued, "--not-before", not_before,
                "--expires-at", expires,
                "--key-id", "oslo-leader-authority-2026",
                "--private-key-environment", "PDR_TEST_LEADER_KEY",
                "--operator", "ha.operator", *leader_trust,
            ]
            racers = [subprocess.Popen(
                [sys.executable, str(LEADER_TOOL), *fence_arguments],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=environment,
            ) for _ in range(2)]
            raced = [process.communicate(timeout=15) + (process.returncode,)
                     for process in racers]
            self.assertEqual(
                sorted(item[2] for item in raced), [0, 2], repr(raced)
            )
            successful = next(item for item in raced if item[2] == 0)
            grant2_sha = successful[0].strip().rsplit("sha256=", 1)[1]
            fenced = publish()
            self.assertEqual(fenced.returncode, 2, fenced.stdout + fenced.stderr)
            self.assertIn("fencing token is stale", fenced.stderr)

            renewed_grant = issue("leadership", 2, grant2_sha)
            self.assertEqual(
                renewed_grant.returncode, 0,
                renewed_grant.stdout + renewed_grant.stderr,
            )
            grant3_sha = renewed_grant.stdout.strip().rsplit("sha256=", 1)[1]
            renewal = self.invoke(
                LEADER_TOOL, "activate", "--registry", str(registry),
                "--node-id", "primary-oslo-01", *backend_args,
                "--authority-id", "registry-leader-authority",
                "--expected-current-grant-sha256", grant3_sha,
                "--operator", "ha.operator", "--operation-audit",
                str(root / "leader-audit.jsonl"),
                "--trust-policy", str(package_policy),
                "--expected-trust-policy-id", "registry-unit-policy",
                "--expected-trust-policy-sha256", package_policy_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
                "--leader-verification-time", now.isoformat(), *leader_trust,
                environment=environment,
            )
            self.assertEqual(renewal.returncode, 0, renewal.stdout + renewal.stderr)
            self.assertIn("operation=renew", renewal.stdout)
            published = publish()
            self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
            pointer = json.loads((registry / "registry.json").read_bytes())
            environment["PDR_TEST_LEADER_BACKEND_MODE"] = "commit-then-timeout"
            uncertain = issue("fence", 3, grant3_sha)
            self.assertEqual(
                uncertain.returncode, 3, uncertain.stdout + uncertain.stderr
            )
            self.assertIn("COMMITTED_ERROR", uncertain.stderr)
            self.assertIn("CAS committed but read-back failed", uncertain.stderr)
            environment["PDR_TEST_LEADER_BACKEND_MODE"] = "normal"
            external_current = (
                backend_root / "registry-leader-authority" /
                "unit-registry" / "current.json"
            )
            grant4_sha = hashlib.sha256(external_current.read_bytes()).hexdigest()
            uncertain_fence = publish()
            self.assertEqual(
                uncertain_fence.returncode, 2,
                uncertain_fence.stdout + uncertain_fence.stderr,
            )
            self.assertIn("fencing token is stale", uncertain_fence.stderr)
            recovered_grant = issue("leadership", 4, grant4_sha)
            self.assertEqual(
                recovered_grant.returncode, 0,
                recovered_grant.stdout + recovered_grant.stderr,
            )
            grant5_sha = recovered_grant.stdout.strip().rsplit("sha256=", 1)[1]
            recovered = self.invoke(
                LEADER_TOOL, "activate", "--registry", str(registry),
                "--node-id", "primary-oslo-01", *backend_args,
                "--authority-id", "registry-leader-authority",
                "--expected-current-grant-sha256", grant5_sha,
                "--operator", "ha.operator", "--operation-audit",
                str(root / "leader-audit.jsonl"),
                "--trust-policy", str(package_policy),
                "--expected-trust-policy-id", "registry-unit-policy",
                "--expected-trust-policy-sha256", package_policy_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
                "--leader-verification-time", now.isoformat(), *leader_trust,
                environment=environment,
            )
            self.assertEqual(
                recovered.returncode, 0, recovered.stdout + recovered.stderr
            )
            status = self.invoke(
                PDR_TOOL, "contract-package", "registry-leader-status",
                "--registry", str(registry),
                "--verification-time", now.isoformat(), environment=environment,
            )
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
            self.assertIn("token=5", status.stdout)
            print(
                "PDR_REGISTRY_LEADER_BACKEND_PASS external=1 cas=1 timeout=1 "
                "mismatch=1 pin=1 secret=1 uncertain=1 fence=1 history=1 "
                "recovery=1"
            )


if __name__ == "__main__":
    unittest.main()
