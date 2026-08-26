import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class BundleRepositoryPublisherTests(unittest.TestCase):
    publisher: Path
    checker: Path
    verifier: Path
    python: Path

    def test_signs_exact_native_fingerprint_and_rejects_repository_overlap(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding, NoEncryption, PrivateFormat, PublicFormat,
            )
        except ImportError as error:
            self.fail(f"release-host cryptography is required: {error}")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "bundles"
            evidence = root / "evidence"
            repository.mkdir()
            (repository / "candidate.bndl").write_bytes(b"candidate-v1")
            sbom = root / "pocoddsruntime.spdx.json"
            sbom_document = {
                "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0",
                "SPDXID": "SPDXRef-DOCUMENT",
                "documentNamespace": "https://pocodds.local/spdx/test",
                "packages": [{"name": "PocoDDSRuntime", "versionInfo": "0.1.0"}],
            }
            sbom.write_text(json.dumps(sbom_document, indent=2), encoding="utf-8")
            artifact = repository / "candidate.bndl"
            entries = [{
                "path": "bundles/candidate.bndl", "size": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }]
            artifact_set = hashlib.sha256(json.dumps(
                entries, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            manifest = root / "SHA256SUMS.json"
            manifest.write_text(json.dumps({
                "schemaVersion": 1, "product": "PocoDDSRuntime", "version": "0.1.0",
                "gitCommit": "1" * 40, "dirty": False,
                "generatedAt": "2026-08-25T00:00:00+00:00", "files": entries,
                "sbom": {"path": sbom.name,
                         "sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
                         "spdxVersion": "SPDX-2.3",
                         "documentNamespace": sbom_document["documentNamespace"]},
                "provenance": {"builderId": "test-builder", "buildProfile": "server",
                               "artifactSetSha256": artifact_set,
                               "source": {"gitCommit": "1" * 40, "dirty": False}},
            }, indent=2), encoding="utf-8")
            key = Ed25519PrivateKey.generate()
            private_key = root / "private.pem"
            public_key = root / "public.pem"
            private_key.write_bytes(key.private_bytes(
                Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
            public_key.write_bytes(key.public_key().public_bytes(
                Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
            environment = dict(os.environ)
            environment["PDR_BUNDLE_TEST_PRIVATE_KEY"] = str(private_key)
            command = [
                str(self.python), str(self.publisher), "sign",
                "--repository", str(repository),
                "--fingerprint-executable", str(self.checker),
                "--repository-id", "runtime-main",
                "--rollout-sequence", "17",
                "--publisher-id", "vendor",
                "--key-id", "vendor-2026",
                "--private-key-path-environment", "PDR_BUNDLE_TEST_PRIVATE_KEY",
                "--output-directory", str(evidence),
                "--release-manifest", str(manifest),
                "--release-sbom", str(sbom),
                "--release-artifacts-root", str(root),
            ]
            result = subprocess.run(command, capture_output=True, text=True,
                                    env=environment, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            digest = report["candidateDigest"]
            attestation = evidence / f"{digest}.attestation.json"
            signature = evidence / f"{digest}.sig.json"
            self.assertTrue(attestation.is_file())
            self.assertTrue(signature.is_file())
            attestation_document = json.loads(attestation.read_text(encoding="utf-8"))
            self.assertEqual(attestation_document["rolloutSequence"], 17)
            self.assertEqual(attestation_document["provenance"]["gitCommit"], "1" * 40)
            self.assertEqual(attestation_document["provenance"]["sbomSha256"],
                             hashlib.sha256(sbom.read_bytes()).hexdigest())
            self.assertEqual(report["rolloutSequence"], 17)
            self.assertTrue((evidence / f"{digest}.release-manifest.json").is_file())
            self.assertTrue((evidence / f"{digest}.spdx.json").is_file())
            verification = subprocess.run([
                str(self.verifier), str(attestation), str(signature), str(public_key),
                "vendor-2026", "PocoDDSBundleRepository",
            ], capture_output=True, text=True, check=False)
            self.assertEqual(verification.returncode, 0,
                             verification.stdout + verification.stderr)

            original_sbom = sbom.read_bytes()
            sbom.write_bytes(b'{"spdxVersion":"SPDX-2.3","packages":[]}')
            provenance_rejected = subprocess.run(
                command, capture_output=True, text=True, env=environment, check=False
            )
            self.assertEqual(provenance_rejected.returncode, 1)
            self.assertIn("SBOM does not match", provenance_rejected.stderr)
            sbom.write_bytes(original_sbom)

            (repository / "candidate.bndl").write_bytes(b"candidate-v2")
            fingerprint = subprocess.run(
                [str(self.checker), "fingerprint", str(repository)],
                capture_output=True, text=True, check=False)
            self.assertEqual(fingerprint.returncode, 0, fingerprint.stderr)
            self.assertNotIn(digest, fingerprint.stdout)

            overlap = list(command)
            overlap[overlap.index("--output-directory") + 1] = str(repository / "evidence")
            rejected = subprocess.run(overlap, capture_output=True, text=True,
                                      env=environment, check=False)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("must not overlap", rejected.stderr)


if __name__ == "__main__":
    arguments = argparse.ArgumentParser(add_help=False)
    arguments.add_argument("--publisher", type=Path, required=True)
    arguments.add_argument("--checker", type=Path, required=True)
    arguments.add_argument("--verifier", type=Path, required=True)
    arguments.add_argument("--python", type=Path, required=True)
    options, remaining = arguments.parse_known_args()
    BundleRepositoryPublisherTests.publisher = options.publisher.resolve()
    BundleRepositoryPublisherTests.checker = options.checker.resolve()
    BundleRepositoryPublisherTests.verifier = options.verifier.resolve()
    BundleRepositoryPublisherTests.python = options.python.resolve()
    unittest.main(argv=[__file__, *remaining])
