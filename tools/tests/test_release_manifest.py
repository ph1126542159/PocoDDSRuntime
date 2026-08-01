import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


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
            verify_args = argparse.Namespace(manifest=manifest, artifacts=artifacts)
            self.assertEqual(MODULE.verify(verify_args), 0)
            sbom = json.loads((output / "pocoddsruntime.spdx.json").read_text(encoding="utf-8"))
            self.assertEqual(sbom["spdxVersion"], "SPDX-2.3")
            self.assertGreaterEqual(len(sbom["packages"]), 8)
            binary.write_bytes(b"tampered")
            self.assertNotEqual(MODULE.verify(verify_args), 0)


if __name__ == "__main__":
    unittest.main()
