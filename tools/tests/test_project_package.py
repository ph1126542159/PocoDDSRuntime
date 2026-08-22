import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "pdr.py"


class ProjectPackageTests(unittest.TestCase):
    def run_tool(self, *arguments: str, environment=None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    def prepare(self, root: Path) -> tuple[Path, Path, Path]:
        created = self.run_tool(
            "project", "create", "PackagedRobot", "--output", str(root),
            "--version", "1.2.3",
        )
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        project = root / "PackagedRobot"
        generated = self.run_tool(
            "new", "robot-module", "MissionModule", "--output", str(project / "modules")
        )
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        dependency = self.run_tool(
            "project", "dependency", "add", str(project / "pdr-project.yaml"), "VendorSDK",
            "--version", "2.4.1", "--license", "Apache-2.0",
            "--download", "https://example.invalid/vendor-sdk-2.4.1.zip",
        )
        self.assertEqual(dependency.returncode, 0, dependency.stdout + dependency.stderr)
        lock = project / "pdr-project.lock.json"
        resolved = self.run_tool(
            "project", "resolve", str(project / "pdr-project.yaml"), "--output", str(lock)
        )
        self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)
        artifacts = project / "build/install"
        artifacts.mkdir(parents=True)
        (artifacts / "bin").mkdir()
        (artifacts / "bin/pdr-product.bin").write_bytes(b"deterministic-product")
        return project, lock, artifacts

    def create_package(self, project: Path, artifacts: Path, output: Path,
                       *extra: str, environment=None) -> subprocess.CompletedProcess[str]:
        return self.run_tool(
            "project", "package", "create", str(project / "pdr-project.yaml"),
            "--artifacts", str(artifacts), "--output", str(output),
            "--version", "1.2.3", "--source-date-epoch", "1700000000",
            *extra, environment=environment,
        )

    def test_package_is_reproducible_and_contains_spdx_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, artifacts = self.prepare(Path(directory))
            first = project / "build/dist/first.zip"
            second = project / "build/dist/second.zip"
            one = self.create_package(project, artifacts, first)
            two = self.create_package(project, artifacts, second)
            self.assertEqual(one.returncode, 0, one.stdout + one.stderr)
            self.assertEqual(two.returncode, 0, two.stdout + two.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())

            verified = self.run_tool("project", "package", "verify", str(first))
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            with zipfile.ZipFile(first) as archive:
                names = set(archive.namelist())
                self.assertIn("metadata/project.spdx.json", names)
                self.assertIn("payload/bin/pdr-product.bin", names)
                sbom = json.loads(archive.read("metadata/project.spdx.json"))
                package_manifest = json.loads(archive.read("metadata/package-manifest.json"))
                self.assertEqual(package_manifest["template"],
                                 {"id": "pdr-product", "version": 4})
                package_names = {item["name"] for item in sbom["packages"]}
                self.assertIn("PocoDDSRuntime", package_names)
                self.assertIn("VendorSDK", package_names)
                self.assertIn("MissionModule", package_names)

    def test_signed_package_requires_trusted_key_and_detects_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, artifacts = self.prepare(Path(directory))
            package = project / "build/dist/signed.zip"
            environment_name = "PDR_TEST_PROJECT_PACKAGE_KEY"
            environment = dict(os.environ)
            environment[environment_name] = base64.b64encode(bytes(range(32))).decode("ascii")
            created = self.create_package(
                project, artifacts, package,
                "--signing-key-environment", environment_name,
                "--signing-key-id", "project-release-2026",
                environment=environment,
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            verified = self.run_tool(
                "project", "package", "verify", str(package), "--require-signature",
                "--trusted-key-environment", environment_name,
                "--expected-key-id", "project-release-2026", environment=environment,
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            wrong_identity = self.run_tool(
                "project", "package", "verify", str(package), "--require-signature",
                "--trusted-key-environment", environment_name,
                "--expected-key-id", "wrong-key", environment=environment,
            )
            self.assertNotEqual(wrong_identity.returncode, 0)

            tampered = project / "build/dist/tampered.zip"
            with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
                for info in source.infolist():
                    content = source.read(info)
                    if info.filename == "payload/bin/pdr-product.bin":
                        content = b"tampered-product"
                    target.writestr(info, content)
            rejected = self.run_tool(
                "project", "package", "verify", str(tampered), "--require-signature",
                "--trusted-key-environment", environment_name,
                "--expected-key-id", "project-release-2026", environment=environment,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("package entry changed", rejected.stderr)

    def test_stale_source_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, artifacts = self.prepare(Path(directory))
            source = project / "modules/MissionModule/src/MissionModule.cpp"
            source.write_text(source.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
            result = self.create_package(project, artifacts, project / "build/dist/stale.zip")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("project source tree changed after lock", result.stderr)

    def test_package_version_must_match_project_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, artifacts = self.prepare(Path(directory))
            result = self.run_tool(
                "project", "package", "create", str(project / "pdr-project.yaml"),
                "--artifacts", str(artifacts),
                "--output", str(project / "build/dist/wrong-version.zip"),
                "--version", "9.9.9", "--source-date-epoch", "1700000000",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match project version", result.stderr)

    def test_template_drift_is_rejected_before_release_packaging(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, artifacts = self.prepare(Path(directory))
            readme = project / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8") + "\ncustom drift\n",
                              encoding="utf-8")
            result = self.create_package(
                project, artifacts, project / "build/dist/template-drift.zip"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("project template is not release-ready", result.stderr)

    def test_ed25519_package_uses_pinned_public_key(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            self.skipTest("cryptography is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            project, _, artifacts = self.prepare(Path(directory))
            private_key = project / "build/private.pem"
            public_key = project / "build/public.pem"
            key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
            private_key.write_bytes(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
            public_key.write_bytes(key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
            environment_name = "PDR_TEST_PROJECT_ED25519_KEY"
            environment = dict(os.environ, **{environment_name: str(private_key)})
            package = project / "build/dist/ed25519.zip"
            created = self.create_package(
                project, artifacts, package,
                "--ed25519-private-key-environment", environment_name,
                "--signing-key-id", "project-ed25519-2026", environment=environment,
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            public_digest = hashlib.sha256(public_key.read_bytes()).hexdigest()
            verified = self.run_tool(
                "project", "package", "verify", str(package), "--require-signature",
                "--public-key", str(public_key),
                "--expected-public-key-sha256", public_digest,
                "--expected-key-id", "project-ed25519-2026",
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            rejected = self.run_tool(
                "project", "package", "verify", str(package), "--require-signature",
                "--public-key", str(public_key),
                "--expected-public-key-sha256", "0" * 64,
                "--expected-key-id", "project-ed25519-2026",
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("public key SHA-256 is not trusted", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
