#!/usr/bin/env python3

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
STANDBY_TOOL = TOOLS / "team_contract_registry_standby.py"
RECOVERY_TOOL = TOOLS / "team_contract_registry_recovery.py"
PROVENANCE_TOOL = TOOLS / "team_contract_provenance.py"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_team_contract_provenance as provenance_test  # noqa: E402
import test_team_contract_registry as registry_test  # noqa: E402


class TeamContractRegistryStandbyTests(unittest.TestCase):
    @staticmethod
    def invoke(path: Path, *arguments: str,
               environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(path), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    def test_standby_fast_forwards_and_rejects_local_writes_or_stale_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = registry_test.TeamContractRegistryTests()
            source, trust_policy, trust_sha, package_environment = \
                helper.initialized(root)
            package1 = helper.create_package(
                root, "1.0.0", "1.0.0", package_environment
            )
            self.assertEqual(
                helper.publish(source, trust_policy, trust_sha, package1).returncode, 0
            )
            provenance = provenance_test.TeamContractProvenanceTests()
            _, anchor_policy, anchor_policy_sha, anchor_environment = \
                provenance.anchor_fixture(root / "external-anchor")
            registry_trust = registry_test.TeamContractRegistryTests.common(
                source, trust_policy, trust_sha
            )[2:]
            trust = [
                "--trust-policy", str(trust_policy),
                "--expected-trust-policy-id", "registry-unit-policy",
                "--expected-trust-policy-sha256", trust_sha,
                "--anchor-policy", str(anchor_policy),
                "--expected-anchor-policy-id", "product-registry-auditors",
                "--expected-anchor-policy-sha256", anchor_policy_sha,
                "--verification-time", "2026-08-25T12:30:00Z",
            ]

            def recovery(revision: int) -> tuple[Path, str]:
                anchor = root / "external-anchor" / f"anchor-{revision}.json"
                anchored = self.invoke(
                    PROVENANCE_TOOL, "registry-anchor", "--registry", str(source),
                    "--anchor-id", f"standby-anchor-{revision:04d}",
                    "--anchor-service-id", "external.audit.service",
                    "--key-id", "registry-audit-anchor-2026",
                    "--private-key-environment", "PDR_TEST_ANCHOR_KEY",
                    "--issued-at", f"2026-08-25T12:{10 + revision:02d}:00Z",
                    "--output", str(anchor), *registry_trust,
                    environment=anchor_environment,
                )
                self.assertEqual(anchored.returncode, 0, anchored.stderr)
                output = root / "recovery" / f"registry-{revision}.pdrregistry"
                created = self.invoke(
                    RECOVERY_TOOL, "create", "--registry", str(source),
                    "--recovery-point-id", f"standby-recovery-{revision:04d}",
                    "--anchor", str(anchor), "--operator", "standby.publisher",
                    "--created-at", f"2026-08-25T12:{20 + revision:02d}:00Z",
                    "--output", str(output), *trust,
                )
                self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
                return output, hashlib.sha256(output.read_bytes()).hexdigest()

            recovery1, recovery1_sha = recovery(1)
            standby = root / "standby"
            audit = root / "standby-operations.jsonl"
            initialized = self.invoke(
                STANDBY_TOOL, "init", "--recovery-point", str(recovery1),
                "--expected-recovery-point-sha256", recovery1_sha,
                "--destination", str(standby), "--standby-id", "standby-oslo-01",
                "--operator", "standby.operator", "--operation-audit", str(audit),
                "--updated-at", "2026-08-25T12:25:00Z", *trust,
            )
            self.assertEqual(
                initialized.returncode, 0, initialized.stdout + initialized.stderr
            )
            marker1_path = standby / ".pdr-standby.json"
            marker1_bytes = marker1_path.read_bytes()
            marker1 = json.loads(marker1_bytes)
            self.assertEqual(marker1["syncGeneration"], 1)
            rejected_write = helper.publish(
                standby, trust_policy, trust_sha,
                helper.create_package(root, "1.1.0", "1.1.0", package_environment),
            )
            self.assertEqual(rejected_write.returncode, 2)
            self.assertIn("standby is read-only", rejected_write.stderr)

            package2 = helper.create_package(
                root, "1.2.0", "1.2.0", package_environment
            )
            self.assertEqual(
                helper.publish(source, trust_policy, trust_sha, package2).returncode, 0
            )
            recovery2, recovery2_sha = recovery(2)
            pointer1 = json.loads((standby / "registry.json").read_bytes())
            previous = root / "standby.previous-generation-1"
            unconfirmed = self.invoke(
                STANDBY_TOOL, "sync", "--recovery-point", str(recovery2),
                "--expected-recovery-point-sha256", recovery2_sha,
                "--destination", str(standby), "--standby-id", "standby-oslo-01",
                "--sync-id", "sync-0002", "--operator", "standby.operator",
                "--operation-audit", str(audit), "--previous-output", str(previous),
                "--expected-revision", "1", "--expected-state-sha256",
                pointer1["stateSha256"], "--expected-sync-generation", "1", *trust,
            )
            self.assertEqual(unconfirmed.returncode, 2)
            synced = self.invoke(
                STANDBY_TOOL, "sync", "--recovery-point", str(recovery2),
                "--expected-recovery-point-sha256", recovery2_sha,
                "--destination", str(standby), "--standby-id", "standby-oslo-01",
                "--sync-id", "sync-0002", "--operator", "standby.operator",
                "--operation-audit", str(audit), "--previous-output", str(previous),
                "--expected-revision", "1", "--expected-state-sha256",
                pointer1["stateSha256"], "--expected-sync-generation", "1",
                "--confirm-standby-stopped", "--updated-at",
                "2026-08-25T12:35:00Z", *trust,
            )
            self.assertEqual(synced.returncode, 0, synced.stdout + synced.stderr)
            marker2_path = standby / ".pdr-standby.json"
            marker2 = json.loads(marker2_path.read_bytes())
            self.assertEqual(marker2["syncGeneration"], 2)
            self.assertEqual(marker2["appliedRevision"], 2)
            self.assertEqual(
                marker2["previousMarkerSha256"],
                hashlib.sha256(marker1_bytes).hexdigest(),
            )
            self.assertEqual(
                json.loads((previous / ".pdr-standby.json").read_bytes()), marker1
            )
            status = self.invoke(
                STANDBY_TOOL, "status", "--registry", str(standby), *trust
            )
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)

            stale = self.invoke(
                STANDBY_TOOL, "sync", "--recovery-point", str(recovery1),
                "--expected-recovery-point-sha256", recovery1_sha,
                "--destination", str(standby), "--standby-id", "standby-oslo-01",
                "--sync-id", "sync-stale", "--operator", "standby.operator",
                "--operation-audit", str(audit),
                "--previous-output", str(root / "standby.previous-stale"),
                "--expected-revision", "2", "--expected-state-sha256",
                marker2["appliedStateSha256"], "--expected-sync-generation", "2",
                "--confirm-standby-stopped", *trust,
            )
            self.assertEqual(stale.returncode, 2)
            self.assertIn("not a newer", stale.stderr)
            marker2_bytes = marker2_path.read_bytes()
            marker2["appliedRevision"] = 1
            marker2_path.write_text(json.dumps(marker2) + "\n", encoding="utf-8")
            drift = self.invoke(
                STANDBY_TOOL, "status", "--registry", str(standby), *trust
            )
            self.assertEqual(drift.returncode, 2)
            self.assertIn("diverges", drift.stderr)
            marker2_path.write_bytes(marker2_bytes)
            self.assertEqual(len(audit.read_text(encoding="utf-8").splitlines()), 2)
            print(
                "PDR_REGISTRY_STANDBY_PASS init=1 readOnly=1 fastForward=1 "
                "rollbackArchive=1 stale=1 markerDrift=1"
            )


if __name__ == "__main__":
    unittest.main()
