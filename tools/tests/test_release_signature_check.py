import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


MANIFEST = '{"schemaVersion":1,"product":"PocoDDSRuntime","version":"0.1.0"}\n'
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAebVWLo/mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ=
-----END PUBLIC KEY-----
"""
SIGNATURE = {
    "schemaVersion": 1,
    "product": "PocoDDSRuntime",
    "algorithm": "Ed25519",
    "keyId": "release-test-key",
    "manifestSha256": "1e2f6319bede9abb4c32757c567bcbd51536bbf435a0d8ab5c3acc48398f62a2",
    "signature": "FXg8y92kJLN9E/QZMcrjnDfVCYQ9nzdVK3Ei+PvnxS3uo6jiqGXsaXpVrE8PF/gDarJ8hlcghHSro3D9e5J2Dw==",
}
PLUGIN_ATTESTATION = '{"schemaVersion":1,"product":"PocoDDSRuntimePlugin","publisherId":"test"}\n'
PLUGIN_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAFwN5O2EWe1AH2lJ5E2Z9qHEjrq0wWJ2ABPULLB8HCRo=
-----END PUBLIC KEY-----
"""
PLUGIN_SIGNATURE = {
    "schemaVersion": 1,
    "product": "PocoDDSRuntimePlugin",
    "algorithm": "Ed25519",
    "keyId": "plugin-test-key",
    "manifestSha256": "6950cfd023e8c3e89d1b8c8e2ef43e9461671f84faef7725d6893ce4123b9d71",
    "signature": "cxCNDKBsls4OF2qRoVUyBj4ZnBIp/J4iT38fCjihqYy1q1bUM3ngvjJehIrGtETTuI6PxAjuzbsYSiz0zGwnAw==",
}


class ReleaseSignatureCheckTests(unittest.TestCase):
    executable: Path

    def test_valid_signature_and_fail_closed_tamper_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, envelope, public_key = (
                root / "manifest.json", root / "signature.json", root / "public.pem"
            )
            manifest.write_text(MANIFEST, encoding="utf-8", newline="")
            envelope.write_text(json.dumps(SIGNATURE), encoding="utf-8")
            public_key.write_text(PUBLIC_KEY, encoding="ascii", newline="\n")
            command = [str(self.executable), str(manifest), str(envelope),
                       str(public_key), "release-test-key"]
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SIGNATURE_VERIFY_PASS", result.stdout)

            command[-1] = "revoked-key"
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("key id is not trusted", result.stderr)

            command[-1] = "release-test-key"
            manifest.write_text(MANIFEST.replace("0.1.0", "0.1.1"), encoding="utf-8", newline="")
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("digest mismatch", result.stderr)

            manifest.write_text(MANIFEST, encoding="utf-8", newline="")
            tampered = dict(SIGNATURE)
            tampered["signature"] = "A" + tampered["signature"][1:]
            envelope.write_text(json.dumps(tampered), encoding="utf-8")
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("signature verification failed", result.stderr)

    def test_expected_product_allows_plugin_payload_but_rejects_product_confusion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload, envelope, public_key = (
                root / "attestation.json", root / "signature.json", root / "public.pem")
            payload.write_text(PLUGIN_ATTESTATION, encoding="utf-8", newline="")
            envelope.write_text(json.dumps(PLUGIN_SIGNATURE), encoding="utf-8")
            public_key.write_text(PLUGIN_PUBLIC_KEY, encoding="ascii", newline="\n")
            command = [str(self.executable), str(payload), str(envelope),
                       str(public_key), "plugin-test-key", "PocoDDSRuntimePlugin"]
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            command[-1] = "PocoDDSRuntime"
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("unsupported", result.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    arguments, remaining = parser.parse_known_args()
    ReleaseSignatureCheckTests.executable = arguments.executable.resolve()
    unittest.main(argv=[__file__, *remaining])
