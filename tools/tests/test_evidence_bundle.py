import argparse
import importlib.util
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


TOOL = Path(__file__).resolve().parents[1] / "evidence_bundle.py"
SPEC = importlib.util.spec_from_file_location("evidence_bundle_under_test", TOOL)
assert SPEC and SPEC.loader
BUNDLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUNDLE)


class EvidenceBundleTests(unittest.TestCase):
    verifier = (Path(__file__).resolve().parents[2] / "build/full/bin/pdr-signature-check.exe").resolve()

    def test_signed_bundle_round_trip_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctest = root / "ctest.log"
            local = root / "package.json"
            manifest = root / "SHA256SUMS.json"
            artifacts = root / "artifacts"
            artifacts.mkdir()
            artifact_file = artifacts / "runtime.bin"
            artifact_file.write_bytes(b"runtime")
            ctest.write_text("95 tests passed\n", encoding="utf-8")
            local.write_text('{"passed":true}\n', encoding="utf-8")
            manifest.write_text(json.dumps({"files": [{
                "path": "runtime.bin", "size": artifact_file.stat().st_size,
                "sha256": BUNDLE.digest(artifact_file),
            }]}), encoding="utf-8")
            qualification = root / "qualification.json"
            qualification.write_text(json.dumps({
                "operation": "release-qualification", "passed": True,
                "verdict": "LOCAL_VALIDATION_PASSED", "releaseApproved": False,
                "version": "1.2.3", "git": {"commit": "abc", "worktreeSha256": "def"},
                "tests": {"path": str(ctest)},
                "evidence": [{"name": "package", "path": str(local)}],
                "artifactManifest": {"path": str(manifest), "artifactRoot": str(artifacts)},
                "externalAcceptance": [],
            }), encoding="utf-8")
            key = Ed25519PrivateKey.generate()
            private, public = root / "private.pem", root / "public.pem"
            private.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
            public.write_bytes(key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
            archive, signature = root / "evidence.zip", root / "evidence.sig.json"
            create_args = BUNDLE.parser().parse_args([
                "create", "--qualification", str(qualification), "--include-artifacts",
                "--output", str(archive),
                "--signature-output", str(signature), "--key-id", "release-key",
                "--private-key-path-environment", "PDR_TEST_BUNDLE_PRIVATE_KEY",
            ])
            with mock.patch.dict(os.environ, {"PDR_TEST_BUNDLE_PRIVATE_KEY": str(private)}):
                self.assertEqual(BUNDLE.create(create_args), 0)
            verify_args = BUNDLE.parser().parse_args([
                "verify", "--bundle", str(archive), "--signature", str(signature),
                "--public-key", str(public), "--expected-key-id", "release-key",
                "--expected-public-key-sha256", BUNDLE.digest(public),
                "--signature-check-executable", str(self.verifier),
            ])
            self.assertEqual(BUNDLE.verify(verify_args), 0)
            with zipfile.ZipFile(archive, "a") as changed:
                changed.writestr("unexpected.txt", "tampered")
            with self.assertRaisesRegex(ValueError, "digest mismatch|signature verification failed"):
                BUNDLE.verify(verify_args)


if __name__ == "__main__":
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--verifier", type=Path, required=True)
    parsed, remaining = arguments.parse_known_args()
    EvidenceBundleTests.verifier = parsed.verifier.resolve()
    unittest.main(argv=[__file__, *remaining])
