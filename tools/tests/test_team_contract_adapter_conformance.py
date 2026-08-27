#!/usr/bin/env python3
"""Portable Adapter Conformance Kit tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import team_contract_adapter_conformance as conformance_tool


EXAMPLE = ROOT / "examples" / "team-contract-adapter-config-resolver-file"


class AdapterConformanceTest(unittest.TestCase):
    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def create_resolver(self, work: Path) -> Path:
        target = work / "artifact-config.json"
        target.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractArtifactStoreConfig",
            "storeId": "conformance-target",
        }, sort_keys=True) + "\n", encoding="utf-8")
        config = work / "resolver.json"
        result = subprocess.run([
            sys.executable, str(EXAMPLE / "create_resolver_config.py"),
            "--python", str(Path(sys.executable).resolve()),
            "--adapter", str(
                (EXAMPLE / "file_adapter_config_resolver_adapter.py").resolve()
            ),
            "--resolver-id", "conformance-resolver",
            "--scope", "adapter-catalog-fleet", "rollout-a", "catalog-a",
            "--entry", "artifact.config", "revision-1", "artifact-store",
            str(target.resolve()),
            "--mapping-output", str((work / "mapping.json").resolve()),
            "--output", str(config.resolve()),
        ], check=False, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return config

    def command(self, config: Path, report: Path, digest: str | None = None,
                *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([
            sys.executable, str(TOOLS / "pdr.py"), "contract-package",
            "adapter-conformance", "--adapter-kind",
            "adapter-config-resolver", "--config", str(config),
            "--expected-config-sha256", digest or self.digest(config),
            "--report", str(report), *extra,
        ], check=False, capture_output=True, text=True)

    def test_live_certification_is_stable_redacted_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            work = Path(value).resolve()
            config = self.create_resolver(work)
            report_a = work / "conformance-a.json"
            first = self.command(config, report_a)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertIn("PDR_ADAPTER_CONFORMANCE_PASS", first.stdout)
            evidence_a = json.loads(report_a.read_bytes())
            conformance_tool.validate_evidence(evidence_a)
            self.assertEqual(
                [item["checkId"] for item in evidence_a["checks"]],
                conformance_tool.CHECK_IDS,
            )
            content = report_a.read_text(encoding="utf-8")
            self.assertNotIn(str(config), content)
            self.assertNotIn(str(work / "mapping.json"), content)

            report_b = work / "conformance-b.json"
            second = self.command(config, report_b)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            evidence_b = json.loads(report_b.read_bytes())
            self.assertEqual(
                evidence_a["conformanceId"], evidence_b["conformanceId"]
            )
            self.assertEqual(
                evidence_a["capabilityManifestSha256"],
                evidence_b["capabilityManifestSha256"],
            )

            wrong = ("0" if self.digest(config)[0] != "0" else "1") \
                + self.digest(config)[1:]
            rejected = self.command(config, work / "wrong.json", wrong)
            self.assertEqual(rejected.returncode, 2)
            self.assertFalse((work / "wrong.json").exists())
            out_of_scope = self.command(
                config, work / "scope.json", None,
                "--scope-primary", "unexpected",
            )
            self.assertEqual(out_of_scope.returncode, 2)

            changed = self.digest(config)
            config.write_bytes(config.read_bytes() + b" \n")
            drift = self.command(config, work / "drift.json", changed)
            self.assertEqual(drift.returncode, 2)
            self.assertFalse((work / "drift.json").exists())

            tampered = dict(evidence_a)
            tampered["adapterId"] = "other-adapter"
            with self.assertRaisesRegex(ValueError, "malformed"):
                conformance_tool.validate_evidence(tampered)
            invalid_time = dict(evidence_a, certifiedAt="not-a-time")
            invalid_time["reportSha256"] = conformance_tool._report_digest(
                invalid_time
            )
            with self.assertRaisesRegex(ValueError, "certifiedAt"):
                conformance_tool.validate_evidence(invalid_time)
            invalid_capability = dict(
                evidence_a, requiredCapabilities=["INVALID CAPABILITY"]
            )
            invalid_capability["reportSha256"] = \
                conformance_tool._report_digest(invalid_capability)
            with self.assertRaisesRegex(ValueError, "malformed"):
                conformance_tool.validate_evidence(invalid_capability)
        print(
            "PDR_ADAPTER_CONFORMANCE_KIT_PASS kinds=6 live=1 pins=1 "
            "replay=1 capability=1 stableId=1 drift=1 scope=1 "
            "redaction=1 selfDigest=1 cli=1"
        )

    def test_kind_registry_is_complete_and_ordered(self) -> None:
        self.assertEqual(set(conformance_tool.SUPPORTED_KINDS), {
            "adapter-config-resolver", "artifact-store",
            "control-authorizer", "fleet-executor",
            "registry-leader-backend", "wave-gate",
        })
        self.assertEqual(
            conformance_tool.CHECK_IDS,
            sorted(conformance_tool.CHECK_IDS),
        )


if __name__ == "__main__":
    unittest.main()
