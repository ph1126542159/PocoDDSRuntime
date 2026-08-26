import argparse
import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_manifest", ROOT / "tools/release_manifest.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ReleaseManifestTests(unittest.TestCase):
    def test_generate_verify_and_detect_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            artifacts = base / "artifacts"
            output = base / "release"
            artifacts.mkdir()
            binary = artifacts / "runtime.bin"
            binary.write_bytes(b"release-v1")
            generate_args = argparse.Namespace(
                root=ROOT,
                artifacts=artifacts,
                output=output,
                version="0.1.0",
                require_clean=False,
            )
            self.assertEqual(MODULE.generate(generate_args), 0)
            manifest = output / "SHA256SUMS.json"
            generated = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertFalse(generated["cleanRequired"])
            self.assertEqual(generated["sbom"]["spdxVersion"], "SPDX-2.3")
            self.assertEqual(generated["provenance"]["source"]["gitCommit"],
                             generated["gitCommit"])
            self.assertEqual(generated["provenance"]["artifactSetSha256"],
                             MODULE.artifact_set_digest(generated["files"]))
            verify_args = argparse.Namespace(manifest=manifest, artifacts=artifacts)
            self.assertEqual(MODULE.verify(verify_args), 0)
            sbom = json.loads((output / "pocoddsruntime.spdx.json").read_text(encoding="utf-8"))
            self.assertEqual(sbom["spdxVersion"], "SPDX-2.3")
            self.assertGreaterEqual(len(sbom["packages"]), 8)
            injected = artifacts / "untracked-plugin.dll"
            injected.write_bytes(b"injected")
            self.assertNotEqual(MODULE.verify(verify_args), 0)

    def test_signed_manifest_rejects_tampered_sbom_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            artifacts, output = base / "artifacts", base / "release"
            artifacts.mkdir()
            (artifacts / "runtime.bin").write_bytes(b"release")
            args = argparse.Namespace(
                root=ROOT, artifacts=artifacts, output=output,
                version="0.1.0", require_clean=False,
                builder_id="ci.example/release", build_profile="server",
            )
            self.assertEqual(MODULE.generate(args), 0)
            manifest = output / "SHA256SUMS.json"
            verify_args = argparse.Namespace(manifest=manifest, artifacts=artifacts)
            self.assertEqual(MODULE.verify(verify_args), 0)

            sbom = output / "pocoddsruntime.spdx.json"
            sbom_document = json.loads(sbom.read_text(encoding="utf-8"))
            sbom_document["packages"][0]["versionInfo"] = "9.9.9"
            sbom.write_text(json.dumps(sbom_document), encoding="utf-8")
            self.assertNotEqual(MODULE.verify(verify_args), 0)

            self.assertEqual(MODULE.generate(args), 0)
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["provenance"]["artifactSetSha256"] = "0" * 64
            manifest.write_text(json.dumps(document), encoding="utf-8")
            self.assertNotEqual(MODULE.verify(verify_args), 0)

    def test_require_clean_rejects_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            artifacts = base / "artifacts"
            artifacts.mkdir()
            (artifacts / "runtime.bin").write_bytes(b"release")
            args = argparse.Namespace(
                root=ROOT,
                artifacts=artifacts,
                output=base / "release",
                version="0.1.0",
                require_clean=True,
            )
            with patch.object(
                MODULE, "git_value",
                side_effect=lambda _root, *arguments: (
                    " M tracked.cpp" if arguments[:2] == ("status", "--porcelain")
                    else "test-commit"
                ),
            ):
                self.assertNotEqual(MODULE.generate(args), 0)
            self.assertFalse((base / "release" / "SHA256SUMS.json").exists())

    def test_detached_signature_binds_manifest_and_trusted_key_id(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            artifacts, output = base / "artifacts", base / "release"
            artifacts.mkdir()
            (artifacts / "runtime.bin").write_bytes(b"signed-release")
            key = base64.b64encode(bytes(range(32))).decode("ascii")
            environment = "PDR_TEST_RELEASE_SIGNING_KEY"
            generate_args = argparse.Namespace(
                root=ROOT, artifacts=artifacts, output=output,
                version="0.1.0", require_clean=False,
                signing_key_environment=environment, signing_key_id="test-key-2026",
            )
            with patch.dict("os.environ", {environment: key}):
                self.assertEqual(MODULE.generate(generate_args), 0)
                verify_args = argparse.Namespace(
                    manifest=output / "SHA256SUMS.json", artifacts=artifacts,
                    signature=output / "SHA256SUMS.sig.json",
                    trusted_key_environment=environment,
                    expected_key_id="test-key-2026", require_signature=True,
                )
                self.assertEqual(MODULE.verify(verify_args), 0)
                verify_args.expected_key_id = "untrusted-key"
                self.assertNotEqual(MODULE.verify(verify_args), 0)
                verify_args.expected_key_id = "test-key-2026"
                manifest = json.loads(verify_args.manifest.read_text(encoding="utf-8"))
                manifest["version"] = "9.9.9"
                verify_args.manifest.write_text(json.dumps(manifest), encoding="utf-8")
                self.assertNotEqual(MODULE.verify(verify_args), 0)

    def test_generate_ed25519_signature_from_environment_key_path(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            self.skipTest("release-host cryptography package is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            artifacts, output = base / "artifacts", base / "release"
            artifacts.mkdir()
            (artifacts / "runtime.bin").write_bytes(b"ed25519-release")
            private_key = base / "private.pem"
            private_key.write_bytes(Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33))).private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
            environment = "PDR_TEST_ED25519_PRIVATE_KEY_PATH"
            args = argparse.Namespace(
                root=ROOT, artifacts=artifacts, output=output,
                version="0.1.0", require_clean=False,
                signing_key_environment=None,
                ed25519_private_key_environment=environment,
                private_key_passphrase_environment=None,
                signing_key_id="ed25519-test-key",
            )
            with patch.dict("os.environ", {environment: str(private_key)}):
                self.assertEqual(MODULE.generate(args), 0)
            envelope = json.loads(
                (output / "SHA256SUMS.sig.json").read_text(encoding="utf-8")
            )
            self.assertEqual(envelope["algorithm"], "Ed25519")
            self.assertEqual(envelope["keyId"], "ed25519-test-key")
    def test_verify_rejects_path_traversal_and_duplicate_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            artifacts = base / "artifacts"
            artifacts.mkdir()
            (artifacts / "runtime.bin").write_bytes(b"safe")
            outside = base / "outside.bin"
            outside.write_bytes(b"outside")
            manifest = base / "manifest.json"
            document = {
                "schemaVersion": 1,
                "product": "PocoDDSRuntime",
                "artifactRoot": str(artifacts),
                "files": [
                    {"path": "../outside.bin", "size": 7,
                     "sha256": MODULE.digest(outside)},
                    {"path": "runtime.bin", "size": 4,
                     "sha256": MODULE.digest(artifacts / "runtime.bin")},
                    {"path": "runtime.bin", "size": 4,
                     "sha256": MODULE.digest(artifacts / "runtime.bin")},
                ],
            }
            manifest.write_text(json.dumps(document), encoding="utf-8")
            verify_args = argparse.Namespace(manifest=manifest, artifacts=artifacts)
            self.assertNotEqual(MODULE.verify(verify_args), 0)


if __name__ == "__main__":
    unittest.main()
