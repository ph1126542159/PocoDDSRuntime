#!/usr/bin/env python3

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
PDR = TOOLS / "pdr.py"
EXAMPLE = ROOT / "examples/team-contract-registry-leader-backend-file"
GENERATOR = EXAMPLE / "create_backend_config.py"
ADAPTER = EXAMPLE / "file_backend_adapter.py"
sys.path.insert(0, str(TOOLS))
import team_contract_registry_leader_backend as backend_tool  # noqa: E402


class LeaderBackendCapabilityTests(unittest.TestCase):
    @staticmethod
    def invoke(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *arguments], check=False,
            capture_output=True, text=True, timeout=15,
        )

    @staticmethod
    def write_config(path: Path, document: dict) -> str:
        path.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_v2_negotiates_and_v1_remains_explicit_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            adapter = work / "file_backend_adapter.py"
            shutil.copyfile(ADAPTER, adapter)
            config = work / "backend.json"
            generated = self.invoke(
                str(GENERATOR),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(adapter.resolve()),
                "--backend-id", "capability-backend",
                "--authority-id", "capability-authority",
                "--registry-id", "capability-registry",
                "--output", str(config.resolve()),
            )
            self.assertEqual(
                generated.returncode, 0, generated.stdout + generated.stderr
            )
            document = json.loads(config.read_bytes())
            self.assertEqual(document["schemaVersion"], 2)
            self.assertEqual(document["protocolMajor"], 1)
            config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
            report = work / "capabilities.json"
            accepted = self.invoke(
                str(PDR), "contract-package",
                "registry-leader-backend-capabilities",
                "--backend-config", str(config.resolve()),
                "--expected-backend-config-sha256", config_sha,
                "--authority-id", "capability-authority",
                "--registry-id", "capability-registry",
                "--report", str(report.resolve()),
            )
            self.assertEqual(
                accepted.returncode, 0, accepted.stdout + accepted.stderr
            )
            self.assertIn(
                "PDR_REGISTRY_LEADER_BACKEND_CAPABILITIES_PASS",
                accepted.stdout,
            )
            evidence = json.loads(report.read_bytes())
            self.assertEqual(evidence["protocolMajor"], 1)
            self.assertEqual(evidence["protocolMinor"], 0)
            self.assertEqual(
                evidence["requiredCapabilities"], document["requiredCapabilities"]
            )
            self.assertTrue(
                set(evidence["requiredCapabilities"])
                <= set(evidence["capabilities"])
            )
            self.assertRegex(
                evidence["capabilityManifestSha256"], r"^[0-9a-f]{64}$"
            )

            missing_document = dict(document)
            missing_document["requiredCapabilities"] = sorted([
                *document["requiredCapabilities"], "snapshot-restore",
            ])
            missing = work / "missing.json"
            missing_sha = self.write_config(missing, missing_document)
            rejected_missing = self.invoke(
                str(PDR), "contract-package",
                "registry-leader-backend-capabilities",
                "--backend-config", str(missing.resolve()),
                "--expected-backend-config-sha256", missing_sha,
                "--authority-id", "capability-authority",
                "--registry-id", "capability-registry",
            )
            self.assertEqual(rejected_missing.returncode, 2)
            self.assertIn("required capabilities are missing", rejected_missing.stderr)

            major_document = dict(document, protocolMajor=2)
            major = work / "major.json"
            major_sha = self.write_config(major, major_document)
            rejected_major = self.invoke(
                str(PDR), "contract-package",
                "registry-leader-backend-capabilities",
                "--backend-config", str(major.resolve()),
                "--expected-backend-config-sha256", major_sha,
                "--authority-id", "capability-authority",
                "--registry-id", "capability-registry",
            )
            self.assertEqual(rejected_major.returncode, 2)
            self.assertIn("protocol major is incompatible", rejected_major.stderr)

            minor_document = dict(document, minimumProtocolMinor=1)
            minor = work / "minor.json"
            minor_sha = self.write_config(minor, minor_document)
            rejected_minor = self.invoke(
                str(PDR), "contract-package",
                "registry-leader-backend-capabilities",
                "--backend-config", str(minor.resolve()),
                "--expected-backend-config-sha256", minor_sha,
                "--authority-id", "capability-authority",
                "--registry-id", "capability-registry",
            )
            self.assertEqual(rejected_minor.returncode, 2)
            self.assertIn("protocol minor is below policy", rejected_minor.stderr)

            legacy_document = {
                key: value for key, value in document.items()
                if key not in {
                    "protocolMajor", "minimumProtocolMinor",
                    "requiredCapabilities",
                }
            }
            legacy_document["schemaVersion"] = 1
            legacy = work / "legacy.json"
            legacy_sha = self.write_config(legacy, legacy_document)
            legacy_backend = backend_tool.ExternalCommandBackend(
                legacy, legacy_sha,
                "capability-authority", "capability-registry",
            )
            self.assertIsNone(legacy_backend.capability_manifest)
            legacy_report = self.invoke(
                str(PDR), "contract-package",
                "registry-leader-backend-capabilities",
                "--backend-config", str(legacy.resolve()),
                "--expected-backend-config-sha256", legacy_sha,
                "--authority-id", "capability-authority",
                "--registry-id", "capability-registry",
            )
            self.assertEqual(legacy_report.returncode, 2)
            self.assertIn("does not require capability negotiation", legacy_report.stderr)

            adapter.write_bytes(adapter.read_bytes() + b"\n")
            drift = self.invoke(
                str(PDR), "contract-package",
                "registry-leader-backend-capabilities",
                "--backend-config", str(config.resolve()),
                "--expected-backend-config-sha256", config_sha,
                "--authority-id", "capability-authority",
                "--registry-id", "capability-registry",
            )
            self.assertEqual(drift.returncode, 2)
            self.assertIn("artifact digest changed", drift.stderr)
            print(
                "PDR_REGISTRY_LEADER_BACKEND_CAPABILITY_PASS "
                "v2=1 manifest=1 digest=1 required=1 major=1 minor=1 "
                "legacy=1 drift=1"
            )


if __name__ == "__main__":
    unittest.main()
