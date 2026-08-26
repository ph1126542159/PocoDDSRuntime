#!/usr/bin/env python3

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
PDR_TOOL = TOOLS / "pdr.py"
ADAPTER = Path(__file__).resolve().parent / "fixtures/leader_backend_adapter.py"


class TeamContractRegistryLeaderBackendConformanceTests(unittest.TestCase):
    @staticmethod
    def invoke(*arguments: str, environment: dict[str, str]) \
            -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PDR_TOOL), "contract-package",
             "registry-leader-backend-conformance", *arguments],
            check=False, capture_output=True, text=True, env=environment,
        )

    def test_dedicated_scope_conformance_is_repeatable_evidence_not_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = root / "leader_backend_adapter.py"
            adapter.write_bytes(ADAPTER.read_bytes())
            executable = Path(sys.executable).resolve()
            backend_root = root / "backend-store"
            environment = dict(os.environ, **{
                "PDR_TEST_LEADER_BACKEND_ROOT": str(backend_root),
                "PDR_TEST_LEADER_BACKEND_MODE": "normal",
            })
            config = root / "backend.json"
            config.write_text(json.dumps({
                "schemaVersion": 1,
                "product": "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig",
                "backendId": "adapter-team-conformance",
                "kind": "external-command",
                "authorityIds": [
                    "adapter-team-conformance-authority",
                    "adapter-team-conformance-uncertain-authority",
                ],
                "registryIds": [
                    "adapter-team-conformance-registry",
                    "adapter-team-conformance-uncertain-registry",
                ],
                "executable": str(executable),
                "executableSha256": hashlib.sha256(
                    executable.read_bytes()
                ).hexdigest(),
                "arguments": [str(adapter)],
                "artifactPins": [{
                    "path": str(adapter),
                    "sha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
                }],
                "environmentVariables": [
                    "PDR_TEST_LEADER_BACKEND_ROOT",
                    "PDR_TEST_LEADER_BACKEND_MODE",
                ],
                "timeoutSeconds": 1,
                "maxResponseBytes": 65536,
            }, indent=2) + "\n", encoding="utf-8")
            config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
            common = [
                "--backend-config", str(config),
                "--expected-backend-config-sha256", config_sha,
                "--authority-id", "adapter-team-conformance-authority",
                "--registry-id", "adapter-team-conformance-registry",
            ]
            unconfirmed = self.invoke(*common, environment=environment)
            self.assertEqual(unconfirmed.returncode, 2)
            self.assertIn("explicitly confirmed", unconfirmed.stderr)
            report = root / "conformance.json"
            qualified = self.invoke(
                *common, "--confirm-dedicated-empty-scope",
                "--report", str(report), environment=environment,
            )
            self.assertEqual(
                qualified.returncode, 0, qualified.stdout + qualified.stderr
            )
            self.assertIn("checks=6 token=2", qualified.stdout)
            evidence = json.loads(report.read_bytes())
            self.assertTrue(evidence["passed"])
            self.assertEqual(evidence["finalFencingToken"], 2)
            self.assertEqual(len(evidence["checks"]), 6)
            self.assertEqual(
                {item["id"] for item in evidence["checks"]},
                {
                    "empty-scope", "missing-history", "initial-cas",
                    "stale-cas", "concurrent-cas", "immutable-history",
                },
            )
            self.assertTrue(all(item["passed"] for item in evidence["checks"]))
            rerun = self.invoke(
                *common, "--confirm-dedicated-empty-scope", environment=environment
            )
            self.assertEqual(rerun.returncode, 2)
            self.assertIn("scope is not empty", rerun.stderr)
            self.assertTrue((
                backend_root / "adapter-team-conformance-authority" /
                "adapter-team-conformance-registry" / "current.json"
            ).is_file())

            environment["PDR_TEST_LEADER_BACKEND_MODE"] = "commit-then-timeout"
            uncertain = self.invoke(
                "--backend-config", str(config),
                "--expected-backend-config-sha256", config_sha,
                "--authority-id", "adapter-team-conformance-uncertain-authority",
                "--registry-id", "adapter-team-conformance-uncertain-registry",
                "--confirm-dedicated-empty-scope", environment=environment,
            )
            self.assertEqual(
                uncertain.returncode, 3, uncertain.stdout + uncertain.stderr
            )
            self.assertIn("CONFORMANCE_COMMITTED_ERROR", uncertain.stderr)
            self.assertTrue((
                backend_root / "adapter-team-conformance-uncertain-authority" /
                "adapter-team-conformance-uncertain-registry" / "current.json"
            ).is_file())
            print(
                "PDR_REGISTRY_LEADER_BACKEND_CONFORMANCE_TEST_PASS empty=1 "
                "bytes=1 history=1 stale=1 race=1 evidence=1 rerun=1 "
                "uncertain=1"
            )


if __name__ == "__main__":
    unittest.main()
