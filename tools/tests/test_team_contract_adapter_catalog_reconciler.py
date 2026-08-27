#!/usr/bin/env python3
"""Fault tests for recoverable, health-gated Adapter Catalog reconciliation."""

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
RECONCILER_CONFIG_GENERATOR = EXAMPLE / "create_reconciler_config.py"
LIFECYCLE_ADAPTER = EXAMPLE / "lifecycle_reconciler_adapter.py"


ADAPTER_SOURCE = r'''import argparse,json,sys
p=argparse.ArgumentParser();p.add_argument("--adapter-id",required=True);p.add_argument("--implementation-id",required=True);a=p.parse_args()
r=json.loads(sys.stdin.read())
print(json.dumps({"schemaVersion":1,"product":"PocoDDSRuntimeReconcileTestCapabilityManifest","requestId":r["requestId"],"adapterId":a.adapter_id,"implementationId":a.implementation_id,"protocolMajor":1,"protocolMinor":0,"capabilities":["health-check","reconciled-rollout"]},sort_keys=True))
'''


class AdapterCatalogReconcilerTest(unittest.TestCase):
    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def invoke(*arguments: str, environment: dict[str, str] | None = None) \
            -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *arguments], check=False, capture_output=True,
            text=True, timeout=40, env=environment,
        )

    def create_catalog(self, work: Path, adapter: Path, generation: int) -> Path:
        adapter_id = "reconciled-runtime-adapter"
        config = work / f"adapter-{generation}.json"
        config.write_text(json.dumps({
            "schemaVersion": 1, "product": "PocoDDSRuntimeReconcileTestConfig",
            "adapterId": adapter_id, "kind": "external-command",
            "protocolMajor": 1, "minimumProtocolMinor": 0,
            "requiredCapabilities": ["health-check", "reconciled-rollout"],
            "executable": str(Path(sys.executable).resolve()),
            "executableSha256": self.digest(Path(sys.executable)),
            "arguments": [
                str(adapter.resolve()), "--adapter-id", adapter_id,
                "--implementation-id", f"reconciled-adapter-{generation}",
            ],
            "artifactPins": [{
                "path": str(adapter.resolve()), "sha256": self.digest(adapter),
            }],
            "environmentVariables": [], "optionalEnvironmentVariables": [],
            "timeoutSeconds": 5, "maxResponseBytes": 4096,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest = work / f"manifest-{generation}.json"
        manifest_result = self.invoke(
            str(MANIFEST_GENERATOR), "--config", str(config.resolve()),
            "--manifest-id", f"reconciled-runtime.deploy-{generation}",
            "--adapter-id", adapter_id,
            "--adapter-type", "custom-reconciled-runtime",
            "--owner", "team/runtime-governance",
            "--revision", f"deploy-{generation}",
            "--protocol-id", "pdr.reconcile-test",
            "--identity-field", "adapterId",
            "--capability-request-product",
            "PocoDDSRuntimeReconcileTestCapabilityRequest",
            "--capability-manifest-product",
            "PocoDDSRuntimeReconcileTestCapabilityManifest",
            "--output", str(manifest.resolve()),
        )
        self.assertEqual(
            manifest_result.returncode, 0,
            manifest_result.stdout + manifest_result.stderr,
        )
        catalog = work / f"catalog-{generation}.json"
        catalog_result = self.invoke(
            str(CATALOG_GENERATOR), "--catalog-id", "reconciled-host-adapters",
            "--generation", str(generation),
            "--manifest", str(manifest.resolve()),
            "--output", str(catalog.resolve()),
        )
        self.assertEqual(
            catalog_result.returncode, 0,
            catalog_result.stdout + catalog_result.stderr,
        )
        return catalog

    def create_reconciler_config(self, work: Path) -> Path:
        config = work / "reconciler.json"
        result = self.invoke(
            str(RECONCILER_CONFIG_GENERATOR),
            "--python", str(Path(sys.executable).resolve()),
            "--adapter", str(LIFECYCLE_ADAPTER.resolve()),
            "--reconciler-id", "host-adapter-lifecycle",
            "--optional-environment", "PDR_RECONCILER_HEALTH_MODE",
            "--optional-environment", "PDR_RECONCILER_HEALTH_GATE",
            "--optional-environment", "PDR_RECONCILER_REJECT_OPERATION",
            "--optional-environment", "PDR_RECONCILER_SECRET_SENTINEL",
            "--timeout-seconds", "25", "--health-attempts", "3",
            "--health-interval-milliseconds", "5",
            "--output", str(config.resolve()),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return config

    def bootstrap(self, catalog: Path, state_dir: Path) -> None:
        result = self.invoke(
            str(PDR), "contract-package", "adapter-catalog-activate",
            "--catalog", str(catalog.resolve()),
            "--expected-catalog-sha256", self.digest(catalog),
            "--state-dir", str(state_dir.resolve()),
            "--expected-generation", "0", "--operation-id", "bootstrap-catalog",
            "--actor", "runtime-operator", "--reason", "bootstrap catalog",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def reconcile(self, config: Path, state_dir: Path, transaction_dir: Path,
                  catalog: Path, generation: int, transaction_id: str,
                  report: Path, environment: dict[str, str]) \
            -> subprocess.CompletedProcess[str]:
        return self.invoke(
            str(PDR), "contract-package", "adapter-catalog-reconcile",
            "--config", str(config.resolve()),
            "--expected-config-sha256", self.digest(config),
            "--state-dir", str(state_dir.resolve()),
            "--transaction-dir", str(transaction_dir.resolve()),
            "--transaction-id", transaction_id,
            "--catalog", str(catalog.resolve()),
            "--expected-catalog-sha256", self.digest(catalog),
            "--expected-generation", str(generation),
            "--actor", "runtime-operator",
            "--reason", f"roll out {transaction_id}",
            "--report", str(report.resolve()), environment=environment,
        )

    def recover(self, config: Path, state_dir: Path, transaction_dir: Path,
                transaction_id: str, report: Path,
                environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return self.invoke(
            str(PDR), "contract-package", "adapter-catalog-reconcile-recover",
            "--config", str(config.resolve()),
            "--expected-config-sha256", self.digest(config),
            "--state-dir", str(state_dir.resolve()),
            "--transaction-dir", str(transaction_dir.resolve()),
            "--transaction-id", transaction_id,
            "--report", str(report.resolve()), environment=environment,
        )

    def revert(self, config: Path, state_dir: Path, transaction_dir: Path,
               transaction_id: str, report: Path,
               environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return self.invoke(
            str(PDR), "contract-package", "adapter-catalog-reconcile-revert",
            "--config", str(config.resolve()),
            "--expected-config-sha256", self.digest(config),
            "--state-dir", str(state_dir.resolve()),
            "--transaction-dir", str(transaction_dir.resolve()),
            "--transaction-id", transaction_id,
            "--report", str(report.resolve()), environment=environment,
        )

    @staticmethod
    def current_pointer(state_dir: Path) -> dict[str, object]:
        return json.loads((state_dir / "catalog-state.json").read_bytes())

    def test_health_gate_crash_recovery_and_automatic_rollback(self):
        sentinel = "reconciler-secret-never-report"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            state_dir = work / "catalog-state"
            transaction_dir = work / "reconcile-state"
            lifecycle_state = work / "lifecycle-state"
            adapter = work / "adapter.py"
            adapter.write_text(ADAPTER_SOURCE, encoding="utf-8")
            catalogs = {
                generation: self.create_catalog(work, adapter, generation)
                for generation in range(1, 5)
            }
            config = self.create_reconciler_config(work)
            self.bootstrap(catalogs[1], state_dir)
            environment = dict(os.environ)
            environment["PDR_RECONCILER_STATE_ROOT"] = str(
                lifecycle_state.resolve()
            )
            environment["PDR_RECONCILER_SECRET_SENTINEL"] = sentinel

            report2 = work / "reconcile-2.json"
            deployed2 = self.reconcile(
                config, state_dir, transaction_dir, catalogs[2], 1,
                "deploy-catalog-2", report2, environment,
            )
            self.assertEqual(
                deployed2.returncode, 0, deployed2.stdout + deployed2.stderr
            )
            document2 = json.loads(report2.read_bytes())
            self.assertTrue(document2["passed"])
            self.assertEqual(document2["status"], "committed")
            self.assertEqual(document2["switchedGeneration"], 2)
            self.assertIsNone(document2["rollbackGeneration"])
            self.assertNotIn(sentinel.encode(), report2.read_bytes())
            replay2 = self.reconcile(
                config, state_dir, transaction_dir, catalogs[2], 1,
                "deploy-catalog-2", report2, environment,
            )
            self.assertEqual(replay2.returncode, 0, replay2.stderr)
            collision = self.reconcile(
                config, state_dir, transaction_dir, catalogs[3], 2,
                "deploy-catalog-2", work / "collision.json", environment,
            )
            self.assertEqual(collision.returncode, 2)
            self.assertIn("transaction ID collision", collision.stderr)

            gate = work / "crash-health-gate"
            crash_environment = dict(environment)
            crash_environment["PDR_RECONCILER_HEALTH_GATE"] = str(gate.resolve())
            report3 = work / "reconcile-3.json"
            command3 = [
                sys.executable, str(PDR), "contract-package",
                "adapter-catalog-reconcile", "--config", str(config.resolve()),
                "--expected-config-sha256", self.digest(config),
                "--state-dir", str(state_dir.resolve()),
                "--transaction-dir", str(transaction_dir.resolve()),
                "--transaction-id", "deploy-catalog-3",
                "--catalog", str(catalogs[3].resolve()),
                "--expected-catalog-sha256", self.digest(catalogs[3]),
                "--expected-generation", "2", "--actor", "runtime-operator",
                "--reason", "roll out deploy-catalog-3",
                "--report", str(report3.resolve()),
            ]
            interrupted = subprocess.Popen(
                command3, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=crash_environment,
            )
            started = Path(str(gate.resolve()) + ".started")
            deadline = time.monotonic() + 12
            while not started.exists():
                if time.monotonic() > deadline:
                    interrupted.kill()
                    self.fail("Reconciler did not reach the health gate")
                time.sleep(0.02)
            interrupted.kill()
            interrupted.communicate(timeout=5)
            Path(str(gate.resolve()) + ".release").write_text(
                "release", encoding="utf-8"
            )
            crash_journal = json.loads((
                transaction_dir / "transactions" / "deploy-catalog-3"
                / "journal.json"
            ).read_bytes())
            self.assertEqual(crash_journal["status"], "health-checking")
            self.assertEqual(self.current_pointer(state_dir)["generation"], 3)
            recovered3 = self.recover(
                config, state_dir, transaction_dir, "deploy-catalog-3",
                report3, environment,
            )
            self.assertEqual(
                recovered3.returncode, 0,
                recovered3.stdout + recovered3.stderr,
            )
            document3 = json.loads(report3.read_bytes())
            self.assertEqual(document3["status"], "committed")
            self.assertEqual(self.current_pointer(state_dir)["generation"], 3)
            self.assertEqual(
                document2["capabilityManifestSha256"],
                document3["capabilityManifestSha256"],
            )

            reverted3 = self.revert(
                config, state_dir, transaction_dir, "deploy-catalog-3",
                report3, environment,
            )
            self.assertEqual(
                reverted3.returncode, 0,
                reverted3.stdout + reverted3.stderr,
            )
            reverted3_document = json.loads(report3.read_bytes())
            self.assertEqual(reverted3_document["status"], "rolled-back")
            self.assertEqual(reverted3_document["rollbackGeneration"], 4)
            self.assertEqual(self.current_pointer(state_dir)["generation"], 4)
            replay_revert3 = self.revert(
                config, state_dir, transaction_dir, "deploy-catalog-3",
                report3, environment,
            )
            self.assertEqual(replay_revert3.returncode, 0, replay_revert3.stderr)

            rollback_environment = dict(environment)
            rollback_environment["PDR_RECONCILER_HEALTH_MODE"] = "unhealthy"
            rollback_environment["PDR_RECONCILER_REJECT_OPERATION"] = "rollback"
            report4 = work / "reconcile-4.json"
            failed4 = self.reconcile(
                config, state_dir, transaction_dir, catalogs[4], 4,
                "deploy-catalog-4", report4, rollback_environment,
            )
            self.assertEqual(failed4.returncode, 2)
            failed_document = json.loads(report4.read_bytes())
            self.assertEqual(failed_document["status"], "rollback-failed")
            self.assertEqual(failed_document["switchedGeneration"], 5)
            self.assertEqual(failed_document["rollbackGeneration"], 6)
            self.assertEqual(self.current_pointer(state_dir)["generation"], 6)
            recovered4 = self.recover(
                config, state_dir, transaction_dir, "deploy-catalog-4",
                report4, environment,
            )
            self.assertEqual(recovered4.returncode, 2)
            recovered_document = json.loads(report4.read_bytes())
            self.assertEqual(recovered_document["status"], "rolled-back")
            self.assertFalse(recovered_document["passed"])
            self.assertEqual(recovered_document["healthAttempts"], 3)

            abort_environment = dict(environment)
            abort_environment["PDR_RECONCILER_REJECT_OPERATION"] = "drain"
            abort_report = work / "abort-4.json"
            aborted = self.reconcile(
                config, state_dir, transaction_dir, catalogs[4], 6,
                "abort-catalog-4", abort_report, abort_environment,
            )
            self.assertEqual(aborted.returncode, 2)
            abort_document = json.loads(abort_report.read_bytes())
            self.assertEqual(abort_document["status"], "aborted")
            self.assertIsNone(abort_document["switchedGeneration"])
            self.assertEqual(self.current_pointer(state_dir)["generation"], 6)

            status_report = work / "status.json"
            status = self.invoke(
                str(PDR), "contract-package",
                "adapter-catalog-reconcile-status",
                "--transaction-dir", str(transaction_dir.resolve()),
                "--transaction-id", "deploy-catalog-4",
                "--report", str(status_report.resolve()),
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            status_document = json.loads(status_report.read_bytes())
            self.assertTrue(status_document["terminal"])
            self.assertEqual(status_document["status"], "rolled-back")

            journal_path = (
                transaction_dir / "transactions" / "deploy-catalog-4"
                / "journal.json"
            )
            tampered_journal = json.loads(journal_path.read_bytes())
            tampered_journal["healthAttempt"] += 1
            journal_path.write_text(
                json.dumps(tampered_journal, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            tampered = self.invoke(
                str(PDR), "contract-package",
                "adapter-catalog-reconcile-status",
                "--transaction-dir", str(transaction_dir.resolve()),
                "--transaction-id", "deploy-catalog-4",
            )
            self.assertEqual(tampered.returncode, 2)
        print(
            "PDR_ADAPTER_CATALOG_RECONCILER_PASS protocol=1 prepare=1 drain=1 "
            "switch=1 health=1 commit=1 autoRollback=1 abort=1 journal=1 "
            "crashRecovery=1 rollbackRecovery=1 idempotency=1 collision=1 "
            "snapshot=1 explicitRevert=1 pins=1 redaction=1 capability=1 cli=1"
        )


if __name__ == "__main__":
    unittest.main()
