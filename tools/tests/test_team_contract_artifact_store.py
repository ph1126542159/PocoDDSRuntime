#!/usr/bin/env python3

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
PDR = TOOLS / "pdr.py"
EXAMPLE = ROOT / "examples/team-contract-artifact-store-file"
GENERATOR = EXAMPLE / "create_artifact_store_config.py"
ADAPTER = EXAMPLE / "file_artifact_store_adapter.py"
sys.path.insert(0, str(TOOLS))
import team_contract_artifact_store as artifact_tool  # noqa: E402


class ArtifactStoreTests(unittest.TestCase):
    def test_pinned_content_addressed_store_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = root / "file_artifact_store_adapter.py"
            shutil.copyfile(ADAPTER, adapter)
            config = root / "artifact-store.json"
            environment = dict(os.environ)
            environment["PDR_TEST_ARTIFACT_ROOT"] = str(
                (root / "store").resolve()
            )
            generated = subprocess.run(
                [
                    sys.executable, str(GENERATOR),
                    "--python", str(Path(sys.executable).resolve()),
                    "--adapter", str(adapter.resolve()),
                    "--store-id", "unit-artifacts",
                    "--namespace-id", "migration-artifact-probe",
                    "--root-environment", "PDR_TEST_ARTIFACT_ROOT",
                    "--max-artifact-bytes", "65536",
                    "--output", str(config.resolve()),
                ],
                check=False, capture_output=True, text=True,
                env=environment, timeout=10,
            )
            self.assertEqual(
                generated.returncode, 0, generated.stdout + generated.stderr
            )
            config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
            previous = os.environ.get("PDR_TEST_ARTIFACT_ROOT")
            os.environ["PDR_TEST_ARTIFACT_ROOT"] = environment[
                "PDR_TEST_ARTIFACT_ROOT"
            ]
            try:
                store = artifact_tool.ExternalCommandArtifactStore(
                    config, config_sha, "migration-artifact-probe"
                )
                content = b'{"evidence":"portable","schemaVersion":1}\n'
                reference = store.put(content, "application/json")
                self.assertEqual(reference["kind"], "content-addressed")
                self.assertEqual(reference["storeId"], "unit-artifacts")
                self.assertEqual(
                    reference["sha256"], hashlib.sha256(content).hexdigest()
                )
                self.assertEqual(store.get(reference), content)
                self.assertEqual(store.put(content, "application/json"), reference)
                artifact_path = (
                    root / "store" / "unit-artifacts"
                    / "migration-artifact-probe" / reference["sha256"][:2]
                    / f"{reference['sha256']}.artifact"
                )
                self.assertEqual(artifact_path.read_bytes(), content)
                portable_input = root / "portable-input.json"
                portable_input.write_bytes(b'{"portable":true}\n')
                portable_reference = root / "portable-reference.json"
                put_result = subprocess.run(
                    [
                        sys.executable, str(PDR), "contract-package",
                        "artifact-store-put", "--config", str(config),
                        "--expected-config-sha256", config_sha,
                        "--namespace-id", "migration-artifact-probe",
                        "--input", str(portable_input.resolve()),
                        "--media-type", "application/json",
                        "--reference-output", str(portable_reference.resolve()),
                    ], check=False, capture_output=True, text=True,
                    env=environment, timeout=10,
                )
                self.assertEqual(
                    put_result.returncode, 0,
                    put_result.stdout + put_result.stderr,
                )
                portable_input.unlink()
                portable_output = root / "portable-output.json"
                get_result = subprocess.run(
                    [
                        sys.executable, str(PDR), "contract-package",
                        "artifact-store-get", "--config", str(config),
                        "--expected-config-sha256", config_sha,
                        "--namespace-id", "migration-artifact-probe",
                        "--reference", str(portable_reference.resolve()),
                        "--output", str(portable_output.resolve()),
                    ], check=False, capture_output=True, text=True,
                    env=environment, timeout=10,
                )
                self.assertEqual(
                    get_result.returncode, 0,
                    get_result.stdout + get_result.stderr,
                )
                self.assertEqual(portable_output.read_bytes(), b'{"portable":true}\n')
                missing = dict(reference)
                missing["sha256"] = "f" * 64
                with self.assertRaisesRegex(ValueError, "unavailable"):
                    store.get(missing)
                artifact_path.write_bytes(b"tampered")
                with self.assertRaisesRegex(RuntimeError, "process failed"):
                    store.get(reference)
                with self.assertRaisesRegex(ValueError, "namespace"):
                    artifact_tool.ExternalCommandArtifactStore(
                        config, config_sha, "unauthorized-namespace"
                    )
                adapter.write_text("# drift\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "digest changed"):
                    store.get(reference)
            finally:
                if previous is None:
                    os.environ.pop("PDR_TEST_ARTIFACT_ROOT", None)
                else:
                    os.environ["PDR_TEST_ARTIFACT_ROOT"] = previous
            print(
                "PDR_ARTIFACT_STORE_PASS generated=1 pins=1 capability=1 "
                "put=1 get=1 immutable=1 idempotent=1 missing=1 tamper=1 "
                "namespace=1 drift=1 portableRef=1 cliTransfer=1"
            )


if __name__ == "__main__":
    unittest.main()
