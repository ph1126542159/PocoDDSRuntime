import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/upgrade_manager.py"


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


class UpgradeManagerTests(unittest.TestCase):
    def test_apply_health_and_manual_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, package = root / "runtime", root / "package"
            installed(target, "0.1.0", "old-release")
            package.mkdir()
            (package / "runtime.bin").write_bytes(b"new-release")
            (package / "health.ready").write_text("ready", encoding="utf-8")
            release_manifest, audit = root / "manifest.json", root / "audit.jsonl"
            manifest(package, release_manifest, "0.2.0", ["0.1.0"])
            result = subprocess.run(
                [sys.executable, str(TOOL), "apply", "--package", str(package),
                 "--manifest", str(release_manifest), "--target", str(target),
                 "--audit", str(audit), "--health-file", "health.ready",
                 "--health-timeout", "1"],
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads((target / "pdr-release.json").read_text())["version"], "0.2.0")
            result = subprocess.run(
                [sys.executable, str(TOOL), "rollback", "--target", str(target),
                 "--audit", str(audit)], check=False
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual((target / "old.txt").read_text(encoding="utf-8"), "old-release")
            events = [json.loads(line)["event"] for line in audit.read_text().splitlines()]
            self.assertIn("health_passed", events)
            self.assertIn("manual_rollback", events)

    def test_failed_health_check_automatically_restores_old_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, package = root / "runtime", root / "package"
            installed(target, "0.1.0", "old-release")
            package.mkdir()
            (package / "runtime.bin").write_bytes(b"broken-release")
            release_manifest, audit = root / "manifest.json", root / "audit.jsonl"
            manifest(package, release_manifest, "0.2.0", ["0.1.0"])
            result = subprocess.run(
                [sys.executable, str(TOOL), "apply", "--package", str(package),
                 "--manifest", str(release_manifest), "--target", str(target),
                 "--audit", str(audit), "--health-file", "health.ready",
                 "--health-timeout", "0.2"], check=False
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual((target / "old.txt").read_text(encoding="utf-8"), "old-release")
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
                 "--audit", str(audit)], check=False
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual((target / "old.txt").read_text(encoding="utf-8"), "old-release")


if __name__ == "__main__":
    unittest.main()
