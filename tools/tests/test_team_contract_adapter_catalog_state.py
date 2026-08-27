#!/usr/bin/env python3
"""Fault tests for atomic host-local Adapter Catalog activation and rollback."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
EXAMPLE = ROOT / "examples" / "team-contract-adapter-catalog"
PDR = TOOLS / "pdr.py"
MANIFEST_GENERATOR = EXAMPLE / "create_adapter_manifest.py"
CATALOG_GENERATOR = EXAMPLE / "create_adapter_catalog.py"
sys.path.insert(0, str(TOOLS))
import team_contract_adapter_catalog_state as state_tool  # noqa: E402


ADAPTER_SOURCE = r'''import argparse,json,os,sys,time
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--adapter-id",required=True)
p.add_argument("--implementation-id",required=True)
a=p.parse_args()
request=json.loads(sys.stdin.read())
gate=os.environ.get("PDR_CATALOG_PROBE_GATE")
if gate:
    Path(gate+".started").write_text("started",encoding="utf-8")
    deadline=time.monotonic()+8
    while not Path(gate+".release").exists():
        if time.monotonic()>deadline: raise RuntimeError("probe gate timeout")
        time.sleep(0.02)
secret=os.environ.get("PDR_CATALOG_PROBE_SECRET")
if secret: print(secret,file=sys.stderr)
print(json.dumps({"schemaVersion":1,
 "product":"PocoDDSRuntimeCatalogStateTestCapabilityManifest",
 "requestId":request["requestId"],"adapterId":a.adapter_id,
 "implementationId":a.implementation_id,"protocolMajor":1,"protocolMinor":1,
 "capabilities":["atomic-activation","health-check"]},sort_keys=True))
'''


class AdapterCatalogStateTest(unittest.TestCase):
    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def invoke(*arguments: str, environment: dict[str, str] | None = None) \
            -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *arguments], check=False, capture_output=True,
            text=True, timeout=30, env=environment,
        )

    def build_catalog(self, work: Path, adapter: Path, generation: int) \
            -> tuple[Path, Path]:
        adapter_id = "runtime-audit-adapter"
        config = work / f"adapter-{generation}.json"
        config.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeCatalogStateTestConfig",
            "adapterId": adapter_id, "kind": "external-command",
            "protocolMajor": 1, "minimumProtocolMinor": 0,
            "requiredCapabilities": ["atomic-activation", "health-check"],
            "executable": str(Path(sys.executable).resolve()),
            "executableSha256": self.digest(Path(sys.executable)),
            "arguments": [
                str(adapter.resolve()), "--adapter-id", adapter_id,
                "--implementation-id", f"catalog-state-adapter-{generation}",
            ],
            "artifactPins": [{
                "path": str(adapter.resolve()), "sha256": self.digest(adapter),
            }],
            "environmentVariables": [],
            "optionalEnvironmentVariables": [
                "PDR_CATALOG_PROBE_GATE", "PDR_CATALOG_PROBE_SECRET",
            ],
            "timeoutSeconds": 10, "maxResponseBytes": 4096,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest = work / f"manifest-{generation}.json"
        created_manifest = self.invoke(
            str(MANIFEST_GENERATOR), "--config", str(config.resolve()),
            "--manifest-id", f"runtime-audit.deploy-{generation}",
            "--adapter-id", adapter_id,
            "--adapter-type", "custom-runtime-audit",
            "--owner", "team/runtime-governance",
            "--revision", f"deploy-{generation}",
            "--protocol-id", "pdr.catalog-state-test",
            "--identity-field", "adapterId",
            "--capability-request-product",
            "PocoDDSRuntimeCatalogStateTestCapabilityRequest",
            "--capability-manifest-product",
            "PocoDDSRuntimeCatalogStateTestCapabilityManifest",
            "--output", str(manifest.resolve()),
        )
        self.assertEqual(
            created_manifest.returncode, 0,
            created_manifest.stdout + created_manifest.stderr,
        )
        catalog = work / f"catalog-{generation}.json"
        created_catalog = self.invoke(
            str(CATALOG_GENERATOR), "--catalog-id", "host-runtime-adapters",
            "--generation", str(generation),
            "--manifest", str(manifest.resolve()),
            "--output", str(catalog.resolve()),
        )
        self.assertEqual(
            created_catalog.returncode, 0,
            created_catalog.stdout + created_catalog.stderr,
        )
        return catalog, manifest

    def mutation(self, operation: str, state_dir: Path,
                 expected_generation: int, operation_id: str,
                 *extra: str, report: Path | None = None) \
            -> subprocess.CompletedProcess[str]:
        arguments = [
            str(PDR), "contract-package", f"adapter-catalog-{operation}",
            *extra, "--state-dir", str(state_dir.resolve()),
            "--expected-generation", str(expected_generation),
            "--operation-id", operation_id,
            "--actor", "runtime-operator",
            "--reason", f"catalog {operation} qualification",
        ]
        if report is not None:
            arguments.extend(("--report", str(report.resolve())))
        return self.invoke(*arguments)

    def test_atomic_activation_cas_idempotency_rollback_and_snapshot(self):
        sentinel = "catalog-state-secret-never-report"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            state_dir = work / "state"
            adapter = work / "adapter.py"
            adapter.write_text(ADAPTER_SOURCE, encoding="utf-8")
            catalog1, manifest1 = self.build_catalog(work, adapter, 1)
            catalog2, _ = self.build_catalog(work, adapter, 2)
            catalog3, _ = self.build_catalog(work, adapter, 3)

            activation1 = work / "activation-1.json"
            first = self.mutation(
                "activate", state_dir, 0, "activate-deploy-1",
                "--catalog", str(catalog1.resolve()),
                "--expected-catalog-sha256", self.digest(catalog1),
                report=activation1,
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            first_report = json.loads(activation1.read_bytes())
            self.assertEqual(first_report["generation"], 1)
            self.assertFalse(first_report["idempotentReplay"])

            replay = self.mutation(
                "activate", state_dir, 0, "activate-deploy-1",
                "--catalog", str(catalog1.resolve()),
                "--expected-catalog-sha256", self.digest(catalog1),
                report=activation1,
            )
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertTrue(json.loads(activation1.read_bytes())["idempotentReplay"])
            collision = self.mutation(
                "activate", state_dir, 0, "activate-deploy-1",
                "--catalog", str(catalog2.resolve()),
                "--expected-catalog-sha256", self.digest(catalog2),
            )
            self.assertEqual(collision.returncode, 2)
            self.assertIn("operation ID collision", collision.stderr)
            stale = self.mutation(
                "activate", state_dir, 0, "stale-deploy-2",
                "--catalog", str(catalog2.resolve()),
                "--expected-catalog-sha256", self.digest(catalog2),
            )
            self.assertEqual(stale.returncode, 2)
            self.assertIn("generation changed", stale.stderr)

            activation2 = self.mutation(
                "activate", state_dir, 1, "activate-deploy-2",
                "--catalog", str(catalog2.resolve()),
                "--expected-catalog-sha256", self.digest(catalog2),
            )
            self.assertEqual(
                activation2.returncode, 0, activation2.stdout + activation2.stderr
            )
            downgrade = self.mutation(
                "activate", state_dir, 2, "downgrade-deploy-1",
                "--catalog", str(catalog1.resolve()),
                "--expected-catalog-sha256", self.digest(catalog1),
            )
            self.assertEqual(downgrade.returncode, 2)
            self.assertIn("not an upgrade", downgrade.stderr)

            environment = dict(os.environ)
            environment["PDR_CATALOG_PROBE_SECRET"] = sentinel
            current_check = work / "current-check.json"
            checked = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-current-check",
                "--state-dir", str(state_dir.resolve()),
                "--report", str(current_check.resolve()), environment=environment,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            check_document = json.loads(current_check.read_bytes())
            self.assertEqual(check_document["catalogGeneration"], 2)
            self.assertNotIn(sentinel.encode(), current_check.read_bytes())

            manifest1_content = manifest1.read_bytes()
            manifest1.write_bytes(manifest1_content + b" ")
            unsafe_rollback = self.mutation(
                "rollback", state_dir, 2, "rollback-drifted-deploy-1",
                "--to-generation", "1",
            )
            self.assertEqual(unsafe_rollback.returncode, 2)
            manifest1.write_bytes(manifest1_content)

            rollback_report = work / "rollback.json"
            rolled_back = self.mutation(
                "rollback", state_dir, 2, "rollback-deploy-1",
                "--to-generation", "1", report=rollback_report,
            )
            self.assertEqual(
                rolled_back.returncode, 0,
                rolled_back.stdout + rolled_back.stderr,
            )
            rollback_document = json.loads(rollback_report.read_bytes())
            self.assertEqual(rollback_document["generation"], 3)
            self.assertEqual(rollback_document["catalogGeneration"], 1)
            replay_rollback = self.mutation(
                "rollback", state_dir, 2, "rollback-deploy-1",
                "--to-generation", "1", report=rollback_report,
            )
            self.assertEqual(replay_rollback.returncode, 0, replay_rollback.stderr)
            self.assertTrue(
                json.loads(rollback_report.read_bytes())["idempotentReplay"]
            )

            current = work / "current.json"
            current_result = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-current",
                "--state-dir", str(state_dir.resolve()),
                "--report", str(current.resolve()),
            )
            self.assertEqual(current_result.returncode, 0, current_result.stderr)
            current_document = json.loads(current.read_bytes())
            self.assertEqual(current_document["generation"], 3)
            self.assertEqual(current_document["adapters"][0]["revision"], "deploy-1")

            with state_tool.CatalogStateLease(
                    state_dir.resolve(), "test-contention", "runtime-operator"):
                busy = self.mutation(
                    "activate", state_dir, 3, "lease-contended-deploy-3",
                    "--catalog", str(catalog3.resolve()),
                    "--expected-catalog-sha256", self.digest(catalog3),
                )
            self.assertEqual(busy.returncode, 2)
            self.assertIn("already being modified", busy.stderr)

            gate = work / "probe-gate"
            concurrent_environment = dict(environment)
            concurrent_environment["PDR_CATALOG_PROBE_GATE"] = str(gate.resolve())
            probe = subprocess.Popen(
                [sys.executable, str(PDR), "contract-package",
                 "adapter-catalog-current-check", "--state-dir",
                 str(state_dir.resolve())], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, env=concurrent_environment,
            )
            deadline = time.monotonic() + 8
            while not Path(str(gate.resolve()) + ".started").exists():
                if time.monotonic() > deadline:
                    probe.kill()
                    self.fail("capability probe did not reach the snapshot gate")
                time.sleep(0.02)
            activation3 = self.mutation(
                "activate", state_dir, 3, "activate-deploy-3",
                "--catalog", str(catalog3.resolve()),
                "--expected-catalog-sha256", self.digest(catalog3),
            )
            self.assertEqual(
                activation3.returncode, 0,
                activation3.stdout + activation3.stderr,
            )
            Path(str(gate.resolve()) + ".release").write_text(
                "release", encoding="utf-8"
            )
            probe_stdout, probe_stderr = probe.communicate(timeout=15)
            self.assertEqual(probe.returncode, 2, probe_stdout + probe_stderr)
            self.assertIn("changed during capability check", probe_stderr)

            verification = work / "verification.json"
            verified = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-state-verify",
                "--state-dir", str(state_dir.resolve()),
                "--report", str(verification.resolve()),
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            verification_document = json.loads(verification.read_bytes())
            self.assertEqual(verification_document["stateCount"], 4)
            self.assertEqual(verification_document["catalogBlobCount"], 3)

            pointer = json.loads((state_dir / "catalog-state.json").read_bytes())
            state_path = state_dir / "states" / (
                f"{pointer['generation']:020d}-{pointer['stateSha256']}.state.json"
            )
            state_path.write_bytes(state_path.read_bytes() + b" ")
            tampered = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-state-verify",
                "--state-dir", str(state_dir.resolve()),
            )
            self.assertEqual(tampered.returncode, 2)
        print(
            "PDR_ADAPTER_CATALOG_STATE_PASS state=1 atomic=1 cas=1 lease=1 "
            "idempotency=1 collision=1 monotonic=1 rollback=1 history=1 "
            "transitivePins=1 current=1 capability=1 snapshot=1 integrity=1 "
            "redaction=1 cli=1"
        )


if __name__ == "__main__":
    unittest.main()
