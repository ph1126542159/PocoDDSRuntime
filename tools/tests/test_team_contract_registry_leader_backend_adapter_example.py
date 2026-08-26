#!/usr/bin/env python3

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PDR = ROOT / "tools/pdr.py"
EXAMPLE = ROOT / "examples/team-contract-registry-leader-backend-file"
ADAPTER = EXAMPLE / "file_backend_adapter.py"
CONFIG_TOOL = EXAMPLE / "create_backend_config.py"


class LeaderBackendAdapterExampleTests(unittest.TestCase):
    @staticmethod
    def invoke(*command: str, environment: dict[str, str] | None = None) \
            -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command), check=False, capture_output=True, text=True,
            env=environment, timeout=20,
        )

    def test_generated_config_and_reference_adapter_pass_conformance(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            adapter = work / "file_backend_adapter.py"
            shutil.copyfile(ADAPTER, adapter)
            config = work / "backend.json"
            authority1 = "sample-adapter-authority-0001"
            authority2 = "sample-adapter-authority-0002"
            authority3 = "sample-adapter-authority-0003"
            registry1 = "sample-adapter-registry-0001"
            registry2 = "sample-adapter-registry-0002"
            registry3 = "sample-adapter-registry-0003"
            generated = self.invoke(
                sys.executable, str(CONFIG_TOOL),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(adapter.resolve()),
                "--backend-id", "sample-adapter-backend",
                "--authority-id", authority1,
                "--authority-id", authority2,
                "--authority-id", authority3,
                "--registry-id", registry1,
                "--registry-id", registry2,
                "--registry-id", registry3,
                "--output", str(config.resolve()),
            )
            self.assertEqual(
                generated.returncode, 0, generated.stdout + generated.stderr
            )
            self.assertIn("PDR_LEADER_BACKEND_SAMPLE_CONFIG_PASS", generated.stdout)
            document = json.loads(config.read_bytes())
            self.assertEqual(document["arguments"], [str(adapter.resolve())])
            self.assertEqual(
                document["artifactPins"][0]["sha256"],
                hashlib.sha256(adapter.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                document["environmentVariables"],
                ["PDR_LEADER_BACKEND_SAMPLE_ROOT"],
            )
            overwrite = self.invoke(
                sys.executable, str(CONFIG_TOOL),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(adapter.resolve()),
                "--backend-id", "sample-adapter-backend",
                "--authority-id", authority1,
                "--registry-id", registry1,
                "--output", str(config.resolve()),
            )
            self.assertEqual(overwrite.returncode, 2)

            store = work / "store"
            environment = dict(
                os.environ, PDR_LEADER_BACKEND_SAMPLE_ROOT=str(store.resolve())
            )
            config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
            sys.path.insert(0, str(ROOT / "tools"))
            try:
                import team_contract_package as package_tool
                import team_contract_registry_leader_backend as backend_tool
                empty_backend = backend_tool.ExternalCommandBackend(
                    config, config_sha, authority3, registry3
                )
                stale_candidate = {
                    "fencingToken": 2,
                    "previousGrantSha256": "a" * 64,
                }
                stale_content = package_tool.json_bytes(stale_candidate)
                with mock.patch.dict(os.environ, {
                    "PDR_LEADER_BACKEND_SAMPLE_ROOT": str(store.resolve())
                }):
                    with self.assertRaisesRegex(
                            ValueError, "changed before backend CAS"):
                        empty_backend.compare_and_swap(
                            1, "a" * 64, stale_candidate, stale_content,
                            package_tool.sha256_bytes(stale_content),
                        )
            finally:
                sys.path.pop(0)
            self.assertTrue((store / authority3 / registry3).is_dir())
            self.assertFalse((store / authority3 / registry3 / "current.json").exists())
            report = work / "conformance.json"
            qualified = self.invoke(
                sys.executable, str(PDR), "contract-package",
                "registry-leader-backend-conformance",
                "--backend-config", str(config.resolve()),
                "--expected-backend-config-sha256", config_sha,
                "--authority-id", authority1,
                "--registry-id", registry1,
                "--confirm-dedicated-empty-scope",
                "--report", str(report.resolve()),
                environment=environment,
            )
            self.assertEqual(
                qualified.returncode, 0, qualified.stdout + qualified.stderr
            )
            self.assertIn("checks=6 token=2", qualified.stdout)
            evidence = json.loads(report.read_bytes())
            self.assertEqual(evidence["finalFencingToken"], 2)
            self.assertEqual(len(evidence["checks"]), 6)
            scope = store / authority1 / registry1
            current = json.loads((scope / "current.json").read_bytes())
            self.assertEqual(current["fencingToken"], 2)
            histories = sorted((scope / "grants").glob("*.json"))
            self.assertEqual(len(histories), 2)
            self.assertEqual(
                [json.loads(path.read_bytes())["fencingToken"]
                 for path in histories],
                [1, 2],
            )

            adapter.write_bytes(adapter.read_bytes() + b"\n# tampered\n")
            rejected = self.invoke(
                sys.executable, str(PDR), "contract-package",
                "registry-leader-backend-conformance",
                "--backend-config", str(config.resolve()),
                "--expected-backend-config-sha256", config_sha,
                "--authority-id", authority2,
                "--registry-id", registry2,
                "--confirm-dedicated-empty-scope",
                environment=environment,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("artifact digest changed", rejected.stderr)
            self.assertFalse((store / authority2 / registry2).exists())
            print(
                "PDR_REGISTRY_LEADER_BACKEND_ADAPTER_EXAMPLE_PASS "
                "generated=1 pins=1 overwrite=1 conformance=1 cas=1 "
                "history=1 retained=1 empty-stale=1 tamper=1"
            )


if __name__ == "__main__":
    unittest.main()
