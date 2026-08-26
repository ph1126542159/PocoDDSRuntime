#!/usr/bin/env python3

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
RECOVERY_TOOL = TOOLS / "team_contract_registry_recovery.py"
PROVENANCE_TOOL = TOOLS / "team_contract_provenance.py"
REGISTRY_TOOL = TOOLS / "team_contract_registry.py"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import team_contract_registry_recovery as recovery_module  # noqa: E402
import test_team_contract_provenance as provenance_test  # noqa: E402
import test_team_contract_registry as registry_test  # noqa: E402


class TeamContractRegistryRecoveryTests(unittest.TestCase):
    @staticmethod
    def invoke(path: Path, *arguments: str,
               environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(path), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    def test_anchored_recovery_point_restores_only_to_absent_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = registry_test.TeamContractRegistryTests()
            registry, trust_policy, trust_sha, package_environment = \
                helper.initialized(root)
            package = helper.create_package(
                root, "1.0.0", "1.0.0", package_environment
            )
            published = helper.publish(registry, trust_policy, trust_sha, package)
            self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
            provenance = provenance_test.TeamContractProvenanceTests()
            _, anchor_policy, anchor_policy_sha, anchor_environment = \
                provenance.anchor_fixture(root / "external-anchor")
            anchor = root / "external-anchor" / "registry-anchor.json"
            common = registry_test.TeamContractRegistryTests.common(
                registry, trust_policy, trust_sha
            )[2:]
            anchored = self.invoke(
                PROVENANCE_TOOL, "registry-anchor", "--registry", str(registry),
                "--anchor-id", "recovery-anchor-0001",
                "--anchor-service-id", "external.audit.service",
                "--key-id", "registry-audit-anchor-2026",
                "--private-key-environment", "PDR_TEST_ANCHOR_KEY",
                "--issued-at", "2026-08-25T12:10:00Z",
                "--output", str(anchor), *common, environment=anchor_environment,
            )
            self.assertEqual(anchored.returncode, 0, anchored.stdout + anchored.stderr)
            recovery = root / "offsite" / "unit-registry.pdrregistry"
            create_report = root / "reports" / "create.json"
            verify_report = root / "reports" / "verify.json"
            restore_report = root / "reports" / "restore.json"
            trust = [
                "--trust-policy", str(trust_policy),
                "--expected-trust-policy-id", "registry-unit-policy",
                "--expected-trust-policy-sha256", trust_sha,
                "--anchor-policy", str(anchor_policy),
                "--expected-anchor-policy-id", "product-registry-auditors",
                "--expected-anchor-policy-sha256", anchor_policy_sha,
                "--verification-time", "2026-08-25T12:30:00Z",
            ]
            created = self.invoke(
                RECOVERY_TOOL, "create", "--registry", str(registry),
                "--recovery-point-id", "registry-recovery-0001",
                "--anchor", str(anchor), "--operator", "recovery.operator",
                "--created-at", "2026-08-25T12:20:00Z",
                "--output", str(recovery), "--report", str(create_report), *trust,
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            recovery_sha = hashlib.sha256(recovery.read_bytes()).hexdigest()
            verified = self.invoke(
                RECOVERY_TOOL, "verify", "--recovery-point", str(recovery),
                "--expected-recovery-point-sha256", recovery_sha,
                "--report", str(verify_report), *trust,
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            with zipfile.ZipFile(recovery, "r") as archive:
                manifest = json.loads(archive.read("manifest.json"))
            recovery_module.validate_manifest(manifest)
            recovery_module.validate_report(json.loads(create_report.read_bytes()))
            recovery_module.validate_report(json.loads(verify_report.read_bytes()))
            self.assertEqual(manifest["registryRevision"], 1)
            self.assertEqual(manifest["fileCount"], 4)

            original = recovery.read_bytes()
            recovery.write_bytes(original + b"tampered")
            tampered = self.invoke(
                RECOVERY_TOOL, "verify", "--recovery-point", str(recovery),
                "--expected-recovery-point-sha256", recovery_sha, *trust,
            )
            self.assertEqual(tampered.returncode, 2)
            self.assertIn("digest is not pinned", tampered.stderr)
            recovery.write_bytes(original)

            destination = root / "restored" / "registry"
            audit = root / "restore-audit" / "operations.jsonl"
            unconfirmed = self.invoke(
                RECOVERY_TOOL, "restore", "--recovery-point", str(recovery),
                "--expected-recovery-point-sha256", recovery_sha,
                "--destination", str(destination), "--restore-id", "restore-0001",
                "--operator", "recovery.operator", "--operation-audit", str(audit),
                *trust,
            )
            self.assertEqual(unconfirmed.returncode, 2)
            self.assertFalse(destination.exists())
            restored = self.invoke(
                RECOVERY_TOOL, "restore", "--recovery-point", str(recovery),
                "--expected-recovery-point-sha256", recovery_sha,
                "--destination", str(destination), "--restore-id", "restore-0001",
                "--operator", "recovery.operator", "--operation-audit", str(audit),
                "--confirm-source-unavailable", "--report", str(restore_report), *trust,
            )
            self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
            registry_verified = self.invoke(
                REGISTRY_TOOL, "verify", "--registry", str(destination), *common
            )
            self.assertEqual(
                registry_verified.returncode, 0,
                registry_verified.stdout + registry_verified.stderr,
            )
            audit_document = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
            recovery_module.validate_report(json.loads(restore_report.read_bytes()))
            self.assertEqual(audit_document["operation"], "restore")
            self.assertEqual(audit_document["recoveryPointSha256"], recovery_sha)
            overwrite = self.invoke(
                RECOVERY_TOOL, "restore", "--recovery-point", str(recovery),
                "--expected-recovery-point-sha256", recovery_sha,
                "--destination", str(destination), "--restore-id", "restore-0002",
                "--operator", "recovery.operator", "--operation-audit", str(audit),
                "--confirm-source-unavailable", *trust,
            )
            self.assertEqual(overwrite.returncode, 2)
            self.assertIn("must not exist", overwrite.stderr)

            package2 = helper.create_package(
                root, "1.1.0", "1.1.0", package_environment
            )
            published2 = helper.publish(registry, trust_policy, trust_sha, package2)
            self.assertEqual(published2.returncode, 0)
            stale_anchor = self.invoke(
                RECOVERY_TOOL, "create", "--registry", str(registry),
                "--recovery-point-id", "registry-recovery-stale",
                "--anchor", str(anchor), "--operator", "recovery.operator",
                "--output", str(root / "offsite" / "stale.pdrregistry"), *trust,
            )
            self.assertEqual(stale_anchor.returncode, 2)
            self.assertIn("exact current revision", stale_anchor.stderr)
            print(
                "PDR_REGISTRY_RECOVERY_PASS create=1 verify=1 restore=1 "
                "tamper=1 overwrite=1 staleAnchor=1"
            )


if __name__ == "__main__":
    unittest.main()
