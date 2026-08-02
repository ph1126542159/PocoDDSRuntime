import base64
import hashlib
import hmac
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/upgrade_manager.py"
SPEC = importlib.util.spec_from_file_location("pdr_upgrade_manager", TOOL)
assert SPEC and SPEC.loader
UPGRADE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPGRADE)


def manifest(package: Path, path: Path, version: str, upgrade_from=None) -> None:
    files = []
    for artifact in sorted(package.rglob("*")):
        if artifact.is_file():
            files.append(
                {
                    "path": artifact.relative_to(package).as_posix(),
                    "size": artifact.stat().st_size,
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                }
            )
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "product": "PocoDDSRuntime",
                "version": version,
                "gitCommit": "test-commit",
                "dirty": False,
                "cleanRequired": True,
                "compatibility": {"runtime": version, "upgradeFrom": upgrade_from or []},
                "files": files,
            }
        ),
        encoding="utf-8",
    )


def installed(target: Path, version: str, content: str) -> None:
    target.mkdir()
    (target / "old.txt").write_text(content, encoding="utf-8")
    (target / "pdr-release.json").write_text(
        json.dumps({"version": version}), encoding="utf-8"
    )


def signature(manifest_path: Path, signature_path: Path, key: bytes, key_id: str) -> None:
    content = manifest_path.read_bytes()
    signature_path.write_text(json.dumps({
        "schemaVersion": 1,
        "product": "PocoDDSRuntime",
        "algorithm": "HMAC-SHA256",
        "keyId": key_id,
        "manifestSha256": hashlib.sha256(content).hexdigest(),
        "signature": base64.b64encode(hmac.new(key, content, hashlib.sha256).digest()).decode("ascii"),
    }), encoding="utf-8")


class UpgradeManagerTests(unittest.TestCase):
    def test_transient_windows_rename_lock_is_retried_with_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "source", root / "destination"
            source.mkdir()
            original = Path.rename
            attempts = 0

            def flaky_rename(path: Path, target: Path):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    error = PermissionError("transient sharing violation")
                    error.winerror = 32
                    raise error
                return original(path, target)

            evidence = []
            with patch.object(Path, "rename", new=flaky_rename):
                UPGRADE.rename_path(source, destination, 1.0, evidence, "test-rename")
            self.assertTrue(destination.is_dir())
            self.assertEqual(evidence[0]["attempts"], 3)
            self.assertEqual(evidence[0]["operation"], "test-rename")

    def test_preflight_requires_and_verifies_trusted_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, package = root / "runtime", root / "package"
            installed(target, "0.1.0", "old-release")
            package.mkdir()
            (package / "runtime.bin").write_bytes(b"signed-release")
            release_manifest = root / "manifest.json"
            detached_signature = root / "manifest.sig.json"
            manifest(package, release_manifest, "0.2.0", ["0.1.0"])
            key = bytes(range(32))
            signature(release_manifest, detached_signature, key, "operations-2026")
            environment = "PDR_TEST_TRUSTED_RELEASE_KEY"
            command = [
                sys.executable, str(TOOL), "preflight", "--package", str(package),
                "--manifest", str(release_manifest), "--target", str(target),
                "--signature", str(detached_signature),
                "--trusted-key-environment", environment,
                "--expected-key-id", "operations-2026",
                "--allow-unmanaged-trust",
            ]
            process_environment = os.environ.copy()
            process_environment[environment] = base64.b64encode(key).decode("ascii")
            result = subprocess.run(
                command, env=process_environment,
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(result.stdout)
            self.assertTrue(evidence["signature"]["verified"])
            self.assertEqual(evidence["signature"]["keyId"], "operations-2026")
            command[command.index("--expected-key-id") + 1] = "revoked-key"
            result = subprocess.run(
                command, env=process_environment,
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("key id is not trusted", result.stdout)

    def test_preflight_approves_without_modifying_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, package = root / "runtime", root / "package"
            installed(target, "0.1.0", "old-release")
            package.mkdir()
            (package / "runtime.bin").write_bytes(b"new-release")
            release_manifest, report = root / "manifest.json", root / "preflight.json"
            manifest(package, release_manifest, "0.2.0", ["0.1.0"])
            before = UPGRADE.inventory(target)
            result = subprocess.run(
                [sys.executable, str(TOOL), "preflight", "--package", str(package),
                 "--manifest", str(release_manifest), "--target", str(target),
                 "--report", str(report), "--allow-unsigned-release"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(evidence["verdict"], "APPROVED")
            self.assertEqual(evidence["fromVersion"], "0.1.0")
            self.assertEqual(evidence["toVersion"], "0.2.0")
            self.assertEqual(UPGRADE.inventory(target), before)
            transaction_path, lock_path = UPGRADE.transaction_paths(target)
            self.assertFalse(transaction_path.exists())
            self.assertFalse(lock_path.exists())

    def test_apply_health_and_manual_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, package = root / "runtime", root / "package"
            installed(target, "0.1.0", "old-release")
            obsolete_backup = root / ".runtime.pdr-backup-obsolete"
            installed(obsolete_backup, "0.0.9", "obsolete-release")
            (target / "bin/data").mkdir(parents=True)
            (target / "bin/data/state.db").write_text("state-before", encoding="utf-8")
            (target / "bin/logs").mkdir()
            (target / "bin/logs/runtime.log").write_text("old-log", encoding="utf-8")
            (target / "bin/codeCache").mkdir()
            (target / "bin/codeCache/stale.bin").write_bytes(b"stale")
            package.mkdir()
            (package / "runtime.bin").write_bytes(b"new-release")
            release_manifest, audit = root / "manifest.json", root / "audit.jsonl"
            manifest(package, release_manifest, "0.2.0", ["0.1.0"])
            def publish_health() -> None:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        marker = json.loads((target / "pdr-release.json").read_text(encoding="utf-8"))
                        if marker.get("version") == "0.2.0":
                            (target / "health.ready").write_text("ready", encoding="utf-8")
                            return
                    except (FileNotFoundError, json.JSONDecodeError):
                        pass
                    time.sleep(0.01)
            publisher = threading.Thread(target=publish_health, daemon=True)
            publisher.start()
            result = subprocess.run(
                [sys.executable, str(TOOL), "apply", "--package", str(package),
                 "--manifest", str(release_manifest), "--target", str(target),
                 "--audit", str(audit), "--health-file", "health.ready",
                 "--health-timeout", "1", "--allow-unsigned-release",
                 "--keep-backups", "1"],
                check=False, capture_output=True, text=True,
            )
            publisher.join(timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads((target / "pdr-release.json").read_text())["version"], "0.2.0")
            self.assertEqual((target / "bin/data/state.db").read_text(encoding="utf-8"), "state-before")
            self.assertFalse((target / "bin/codeCache/stale.bin").exists())
            self.assertFalse(obsolete_backup.exists())
            (target / "bin/data/state.db").write_text("state-after", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(TOOL), "rollback", "--target", str(target),
                 "--audit", str(audit)], check=False
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual((target / "old.txt").read_text(encoding="utf-8"), "old-release")
            self.assertEqual((target / "bin/data/state.db").read_text(encoding="utf-8"), "state-after")
            events = [json.loads(line)["event"] for line in audit.read_text().splitlines()]
            self.assertIn("health_passed", events)
            self.assertIn("backup_retention_applied", events)
            self.assertIn("manual_rollback", events)

    def test_failed_health_check_automatically_restores_old_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, package = root / "runtime", root / "package"
            installed(target, "0.1.0", "old-release")
            (target / "data").mkdir()
            (target / "data/state.db").write_text("preserved", encoding="utf-8")
            package.mkdir()
            (package / "runtime.bin").write_bytes(b"broken-release")
            release_manifest, audit = root / "manifest.json", root / "audit.jsonl"
            manifest(package, release_manifest, "0.2.0", ["0.1.0"])
            result = subprocess.run(
                [sys.executable, str(TOOL), "apply", "--package", str(package),
                 "--manifest", str(release_manifest), "--target", str(target),
                 "--audit", str(audit), "--health-file", "health.ready",
                 "--health-timeout", "0.2", "--allow-unsigned-release"], check=False
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual((target / "old.txt").read_text(encoding="utf-8"), "old-release")
            self.assertEqual((target / "data/state.db").read_text(encoding="utf-8"), "preserved")
            self.assertIn("health_failed_rollback", audit.read_text(encoding="utf-8"))

    def test_major_upgrade_requires_explicit_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, package = root / "runtime", root / "package"
            installed(target, "0.9.0", "old-release")
            package.mkdir()
            (package / "runtime.bin").write_bytes(b"major-release")
            release_manifest, audit = root / "manifest.json", root / "audit.jsonl"
            manifest(package, release_manifest, "1.0.0", ["0.9.0"])
            result = subprocess.run(
                [sys.executable, str(TOOL), "apply", "--package", str(package),
                 "--manifest", str(release_manifest), "--target", str(target),
                 "--audit", str(audit), "--allow-unsigned-release"],
                check=False, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("major-version upgrade requires", result.stderr)
            self.assertEqual((target / "old.txt").read_text(encoding="utf-8"), "old-release")

    def test_preflight_rejects_unmanifested_file_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, package = root / "runtime", root / "package"
            package.mkdir()
            (package / "runtime.bin").write_bytes(b"release")
            release_manifest, audit = root / "manifest.json", root / "audit.jsonl"
            manifest(package, release_manifest, "0.2.0")
            (package / "injected.dll").write_bytes(b"injected")
            command = [
                sys.executable, str(TOOL), "apply", "--package", str(package),
                "--manifest", str(release_manifest), "--target", str(target),
                "--audit", str(audit), "--allow-unsigned-release",
            ]
            result = subprocess.run(command, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(target.exists())
            self.assertIn("unexpected artifact", audit.read_text(encoding="utf-8"))

            (package / "injected.dll").unlink()
            document = json.loads(release_manifest.read_text(encoding="utf-8"))
            document["files"][0]["path"] = "../runtime.bin"
            release_manifest.write_text(json.dumps(document), encoding="utf-8")
            result = subprocess.run(command, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(target.exists())
            self.assertIn("unsafe artifact path", audit.read_text(encoding="utf-8"))

    def test_interrupted_activation_recovers_verified_old_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "runtime"
            installed(target, "0.1.0", "old-release")
            (target / "data").mkdir()
            (target / "data/state.db").write_text("before-crash", encoding="utf-8")
            expected = UPGRADE.inventory(target)
            upgrade_id = "interrupted-test"
            backup = root / f".runtime.pdr-backup-{upgrade_id}"
            staging = root / f".runtime.pdr-staging-{upgrade_id}"
            failed = root / f".runtime.pdr-failed-{upgrade_id}"
            audit = root / "audit.jsonl"
            transaction_path, lock_path = UPGRADE.transaction_paths(target)
            target.rename(backup)
            target.mkdir()
            (target / "runtime.bin").write_bytes(b"unverified-new-release")
            (target / "pdr-release.json").write_text(
                json.dumps({"version": "0.2.0"}), encoding="utf-8"
            )
            UPGRADE.transfer_mutable(backup, target)
            (target / "data/state.db").write_text("after-crash", encoding="utf-8")
            UPGRADE.atomic_json(transaction_path, {
                "schemaVersion": UPGRADE.TRANSACTION_SCHEMA_VERSION,
                "upgradeId": upgrade_id,
                "target": str(target), "staging": str(staging),
                "backup": str(backup), "failed": str(failed),
                "audit": str(audit), "fromVersion": "0.1.0",
                "toVersion": "0.2.0", "backupInventory": expected,
                "state": "activated",
            })
            lock_path.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(TOOL), "recover", "--target", str(target)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((target / "old.txt").read_text(encoding="utf-8"), "old-release")
            self.assertEqual((target / "data/state.db").read_text(encoding="utf-8"), "after-crash")
            self.assertFalse(transaction_path.exists())
            self.assertFalse(lock_path.exists())
            event = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(event["event"], "interrupted_upgrade_recovered")
            self.assertEqual(event["outcome"], "old_release_restored")

    def test_recovery_refuses_tampered_backup_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "runtime"
            installed(target, "0.1.0", "old-release")
            expected = UPGRADE.inventory(target)
            upgrade_id = "tamper-test"
            backup = root / f".runtime.pdr-backup-{upgrade_id}"
            staging = root / f".runtime.pdr-staging-{upgrade_id}"
            failed = root / f".runtime.pdr-failed-{upgrade_id}"
            audit = root / "audit.jsonl"
            transaction_path, lock_path = UPGRADE.transaction_paths(target)
            target.rename(backup)
            (backup / "old.txt").write_text("tampered", encoding="utf-8")
            target.mkdir()
            (target / "pdr-release.json").write_text(
                json.dumps({"version": "0.2.0"}), encoding="utf-8"
            )
            UPGRADE.atomic_json(transaction_path, {
                "schemaVersion": UPGRADE.TRANSACTION_SCHEMA_VERSION,
                "upgradeId": upgrade_id,
                "target": str(target), "staging": str(staging),
                "backup": str(backup), "failed": str(failed),
                "audit": str(audit), "fromVersion": "0.1.0",
                "toVersion": "0.2.0", "backupInventory": expected,
                "state": "activated",
            })
            lock_path.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(TOOL), "recover", "--target", str(target)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("integrity verification failed", result.stderr)
            self.assertTrue(transaction_path.exists())
            self.assertTrue(lock_path.exists())
            self.assertEqual(json.loads((target / "pdr-release.json").read_text())["version"], "0.2.0")

    def test_recovery_rejects_transaction_paths_outside_governed_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "runtime"
            installed(target, "0.1.0", "old-release")
            transaction_path, lock_path = UPGRADE.transaction_paths(target)
            upgrade_id = "path-boundary-test"
            outside = root / "outside-evidence"
            outside.mkdir()
            (outside / "keep.txt").write_text("keep", encoding="utf-8")
            UPGRADE.atomic_json(transaction_path, {
                "schemaVersion": UPGRADE.TRANSACTION_SCHEMA_VERSION,
                "upgradeId": upgrade_id,
                "target": str(target),
                "staging": str(root / f".runtime.pdr-staging-{upgrade_id}"),
                "backup": str(root / f".runtime.pdr-backup-{upgrade_id}"),
                "failed": str(outside),
                "audit": str(root / "audit.jsonl"),
                "fromVersion": "0.1.0", "toVersion": "0.2.0",
                "backupInventory": UPGRADE.inventory(target),
                "state": "activated",
            })
            lock_path.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(TOOL), "recover", "--target", str(target)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("outside its governed location", result.stderr)
            self.assertEqual((outside / "keep.txt").read_text(encoding="utf-8"), "keep")
            self.assertTrue(transaction_path.exists())
            self.assertTrue(lock_path.exists())

    def test_apply_rejects_existing_upgrade_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, package = root / "runtime", root / "package"
            installed(target, "0.1.0", "old-release")
            package.mkdir()
            (package / "health.ready").write_text("ready", encoding="utf-8")
            release_manifest, audit = root / "manifest.json", root / "audit.jsonl"
            manifest(package, release_manifest, "0.2.0", ["0.1.0"])
            _, lock_path = UPGRADE.transaction_paths(target)
            lock_path.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(TOOL), "apply", "--package", str(package),
                 "--manifest", str(release_manifest), "--target", str(target),
                 "--audit", str(audit), "--health-file", "health.ready"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("upgrade lock already exists", result.stderr)
            self.assertEqual((target / "old.txt").read_text(encoding="utf-8"), "old-release")


if __name__ == "__main__":
    unittest.main()
