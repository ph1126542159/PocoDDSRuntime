#!/usr/bin/env python3
"""Fault and recovery tests for canary/wave Adapter Catalog Fleet rollout."""

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
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import team_contract_adapter_catalog_fleet as FLEET
EXAMPLE = ROOT / "examples" / "team-contract-adapter-catalog"
PDR = TOOLS / "pdr.py"
MANIFEST_GENERATOR = EXAMPLE / "create_adapter_manifest.py"
CATALOG_GENERATOR = EXAMPLE / "create_adapter_catalog.py"
RECONCILER_CONFIG_GENERATOR = EXAMPLE / "create_reconciler_config.py"
LIFECYCLE_ADAPTER = EXAMPLE / "lifecycle_reconciler_adapter.py"
NODE_MAP_GENERATOR = EXAMPLE / "create_fleet_node_map.py"
EXECUTOR_CONFIG_GENERATOR = EXAMPLE / "create_fleet_executor_config.py"
PLAN_GENERATOR = EXAMPLE / "create_fleet_plan.py"
NODE_EXECUTOR = EXAMPLE / "fleet_node_executor_adapter.py"


ADAPTER_SOURCE = r'''import argparse,json,sys
p=argparse.ArgumentParser();p.add_argument("--adapter-id",required=True);p.add_argument("--implementation-id",required=True);a=p.parse_args()
r=json.loads(sys.stdin.read())
print(json.dumps({"schemaVersion":1,"product":"PocoDDSRuntimeFleetTestCapabilityManifest","requestId":r["requestId"],"adapterId":a.adapter_id,"implementationId":a.implementation_id,"protocolMajor":1,"protocolMinor":0,"capabilities":["fleet-rollout","health-check"]},sort_keys=True))
'''


class AdapterCatalogFleetTest(unittest.TestCase):
    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def invoke(*arguments: str, environment: dict[str, str] | None = None,
               timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *arguments], check=False, capture_output=True,
            text=True, timeout=timeout, env=environment,
        )

    def require_pass(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def create_catalog(self, work: Path, adapter: Path, generation: int) -> Path:
        adapter_id = "fleet-runtime-adapter"
        config = work / f"adapter-{generation}.json"
        config.write_text(json.dumps({
            "schemaVersion": 1, "product": "PocoDDSRuntimeFleetTestConfig",
            "adapterId": adapter_id, "kind": "external-command",
            "protocolMajor": 1, "minimumProtocolMinor": 0,
            "requiredCapabilities": ["fleet-rollout", "health-check"],
            "executable": str(Path(sys.executable).resolve()),
            "executableSha256": self.digest(Path(sys.executable)),
            "arguments": [str(adapter.resolve()), "--adapter-id", adapter_id,
                          "--implementation-id", f"fleet-adapter-{generation}"],
            "artifactPins": [{"path": str(adapter.resolve()),
                              "sha256": self.digest(adapter)}],
            "environmentVariables": [], "optionalEnvironmentVariables": [],
            "timeoutSeconds": 5, "maxResponseBytes": 4096,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest = work / f"manifest-{generation}.json"
        self.require_pass(self.invoke(
            str(MANIFEST_GENERATOR), "--config", str(config.resolve()),
            "--manifest-id", f"fleet-runtime.deploy-{generation}",
            "--adapter-id", adapter_id, "--adapter-type", "custom-fleet-runtime",
            "--owner", "team/runtime-governance", "--revision", f"deploy-{generation}",
            "--protocol-id", "pdr.fleet-test", "--identity-field", "adapterId",
            "--capability-request-product",
            "PocoDDSRuntimeFleetTestCapabilityRequest",
            "--capability-manifest-product",
            "PocoDDSRuntimeFleetTestCapabilityManifest",
            "--output", str(manifest.resolve()),
        ))
        catalog = work / f"catalog-{generation}.json"
        self.require_pass(self.invoke(
            str(CATALOG_GENERATOR), "--catalog-id", "fleet-host-adapters",
            "--generation", str(generation), "--manifest", str(manifest.resolve()),
            "--output", str(catalog.resolve()),
        ))
        return catalog

    def bootstrap(self, catalog: Path, state: Path, node_id: str) -> None:
        self.require_pass(self.invoke(
            str(PDR), "contract-package", "adapter-catalog-activate",
            "--catalog", str(catalog.resolve()),
            "--expected-catalog-sha256", self.digest(catalog),
            "--state-dir", str(state.resolve()), "--expected-generation", "0",
            "--operation-id", f"bootstrap-{node_id}", "--actor", "fleet-test",
            "--reason", "bootstrap Fleet node",
        ))

    @staticmethod
    def wait_for(path: Path, *, status: str | None = None,
                 timeout: float = 25) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.is_file():
                if status is None:
                    return
                try:
                    if json.loads(path.read_bytes()).get("status") == status:
                        return
                except (OSError, json.JSONDecodeError):
                    pass
            time.sleep(0.03)
        raise AssertionError(f"timed out waiting for {path} status={status}")

    def test_recovery_rechecks_budget_after_terminal_batch_journal(self) -> None:
        plan = {
            "schemaVersion": 1,
            "rolloutId": "budget-crash-window", "catalogId": "fleet-catalog",
            "candidateCatalogGeneration": 2,
            "candidateCatalogSha256": "2" * 64,
            "executorConfigSha256": "1" * 64, "maxParallelNodes": 2,
            "waves": [{
                "waveId": "canary", "mode": "canary", "maxFailures": 0,
                "nodes": [
                    {"nodeId": "node-a", "failureDomain": "rack-a",
                     "expectedActivationGeneration": 1},
                    {"nodeId": "node-b", "failureDomain": "rack-b",
                     "expectedActivationGeneration": 1},
                ],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            journal = FLEET.create_journal(plan, "0" * 64, "1" * 64)
            journal["nodes"][0]["status"] = "committed"
            journal["nodes"][1]["status"] = "failed"
            FLEET.write_journal(path, journal)
            with mock.patch.object(FLEET, "rollback_committed") as rollback:
                FLEET.drive(plan, {}, path, journal)
            self.assertEqual(journal["status"], "rolling-back")
            self.assertEqual(journal["failedWave"], 0)
            rollback.assert_called_once()

    def test_canary_wave_crash_budget_and_reverse_rollback(self) -> None:
        sentinel = "fleet-secret-never-persist"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve()
            adapter = work / "adapter.py"
            adapter.write_text(ADAPTER_SOURCE, encoding="utf-8")
            catalog1 = self.create_catalog(work, adapter, 1)
            catalog2 = self.create_catalog(work, adapter, 2)
            reconciler_config = work / "reconciler.json"
            self.require_pass(self.invoke(
                str(RECONCILER_CONFIG_GENERATOR), "--python",
                str(Path(sys.executable).resolve()), "--adapter",
                str(LIFECYCLE_ADAPTER.resolve()), "--reconciler-id",
                "fleet-node-lifecycle", "--optional-environment",
                "PDR_RECONCILER_HEALTH_MODE", "--optional-environment",
                "PDR_RECONCILER_SECRET_SENTINEL", "--timeout-seconds", "20",
                "--health-attempts", "1", "--output",
                str(reconciler_config.resolve()),
            ))
            nodes: dict[str, dict[str, Path]] = {}
            for node_id in ("node-a", "node-b", "node-c", "node-d"):
                state = work / node_id / "state"
                state.mkdir(parents=True)
                self.bootstrap(catalog1, state, node_id)
                nodes[node_id] = {
                    "state": state, "transactions": work / node_id / "transactions",
                    "lifecycle": work / node_id / "lifecycle",
                }
            mapping = work / "fleet-node-map.json"
            map_args = [
                str(NODE_MAP_GENERATOR), "--executor-id", "local-fleet-executor",
                "--audit", str((work / "fleet-audit.log").resolve()),
            ]
            for node_id in sorted(nodes):
                paths = nodes[node_id]
                map_args.extend([
                    "--node", node_id, str(paths["state"].resolve()),
                    str(paths["transactions"].resolve()),
                    str(paths["lifecycle"].resolve()),
                    str(reconciler_config.resolve()), str(catalog2.resolve()), "1",
                    "unhealthy" if node_id == "node-c" else "healthy",
                ])
            map_args.extend(["--output", str(mapping.resolve())])
            self.require_pass(self.invoke(*map_args))
            executor_config = work / "fleet-executor.json"
            config_args = [
                str(EXECUTOR_CONFIG_GENERATOR), "--python",
                str(Path(sys.executable).resolve()), "--adapter",
                str(NODE_EXECUTOR.resolve()), "--mapping", str(mapping.resolve()),
                "--tools-dir", str(TOOLS.resolve()), "--executor-id",
                "local-fleet-executor",
            ]
            for name in (
                    "PDR_FLEET_EXECUTOR_GATE", "PDR_FLEET_EXECUTOR_GATE_NODE",
                    "PDR_FLEET_EXECUTOR_SECRET_SENTINEL"):
                config_args.extend(["--optional-environment", name])
            config_args.extend(["--timeout-seconds", "35", "--output",
                                str(executor_config.resolve())])
            self.require_pass(self.invoke(*config_args))
            plan = work / "fleet-plan.json"
            self.require_pass(self.invoke(
                str(PLAN_GENERATOR), "--rollout-id", "fleet-upgrade-2",
                "--catalog", str(catalog2.resolve()), "--executor-config",
                str(executor_config.resolve()), "--max-parallel-nodes", "2",
                "--wave", "canary", "canary", "0",
                "--wave", "wave-1", "wave", "0",
                "--node", "canary", "node-a", "rack-a", "1",
                "--node", "wave-1", "node-b", "rack-b", "1",
                "--node", "wave-1", "node-c", "rack-c", "1",
                "--node", "wave-1", "node-d", "rack-d", "1",
                "--output", str(plan.resolve()),
            ))
            fleet_state = work / "fleet-state"
            report = work / "fleet-report.json"
            gate = work / "node-b-response-gate"
            environment = os.environ.copy()
            environment.update({
                "PDR_FLEET_EXECUTOR_GATE": str(gate),
                "PDR_FLEET_EXECUTOR_GATE_NODE": "node-b",
                "PDR_FLEET_EXECUTOR_SECRET_SENTINEL": sentinel,
            })
            command = [
                sys.executable, str(PDR), "contract-package",
                "adapter-catalog-fleet-run", "--plan", str(plan.resolve()),
                "--expected-plan-sha256", self.digest(plan), "--executor-config",
                str(executor_config.resolve()),
                "--expected-executor-config-sha256", self.digest(executor_config),
                "--state-dir", str(fleet_state.resolve()), "--report",
                str(report.resolve()),
            ]
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=environment,
            )
            transaction_id = "fleet-upgrade-2"
            b_journal = nodes["node-b"]["transactions"] / "transactions" / \
                f"{transaction_id}.node-b" / "journal.json"
            c_journal = nodes["node-c"]["transactions"] / "transactions" / \
                f"{transaction_id}.node-c" / "journal.json"
            release = Path(str(gate) + ".release")
            try:
                self.wait_for(Path(str(gate) + ".started"))
                self.wait_for(b_journal, status="committed")
                # Existence proves the peer entered the same parallel batch;
                # it need not finish before the coordinator is killed.
                self.wait_for(c_journal)
                process.kill()
                process.communicate(timeout=10)
                release.write_text("release", encoding="utf-8")
            finally:
                release.write_text("release", encoding="utf-8")
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=10)
            time.sleep(0.2)
            deadline = time.monotonic() + 60
            while True:
                recover = self.invoke(
                    str(PDR), "contract-package", "adapter-catalog-fleet-recover",
                    "--plan", str(plan.resolve()), "--expected-plan-sha256",
                    self.digest(plan), "--executor-config",
                    str(executor_config.resolve()),
                    "--expected-executor-config-sha256",
                    self.digest(executor_config), "--state-dir",
                    str(fleet_state.resolve()), "--report", str(report.resolve()),
                    environment=environment,
                )
                if report.is_file() and json.loads(report.read_bytes()).get(
                        "status") == "rolled-back":
                    break
                if time.monotonic() >= deadline:
                    self.fail(
                        "Fleet recovery did not resolve ambiguous node result: "
                        + recover.stdout + recover.stderr
                    )
                time.sleep(0.1)
            self.assertEqual(recover.returncode, 2, recover.stdout + recover.stderr)
            document = json.loads(report.read_bytes())
            self.assertEqual(document["status"], "rolled-back")
            self.assertFalse(document["passed"])
            self.assertEqual(document["rolledBackNodes"], 2)
            self.assertEqual(document["failedNodes"], 1)
            self.assertEqual(document["pendingNodes"], 1)
            self.assertNotIn(sentinel, report.read_text(encoding="utf-8"))
            journal_path = fleet_state / "rollouts" / transaction_id / "journal.json"
            journal = json.loads(journal_path.read_bytes())
            self.assertNotIn(sentinel, json.dumps(journal))
            by_node = {node["nodeId"]: node["status"] for node in journal["nodes"]}
            self.assertEqual(by_node, {
                "node-a": "rolled-back", "node-b": "rolled-back",
                "node-c": "failed", "node-d": "pending",
            })
            for node_id, expected in (
                    ("node-a", 3), ("node-b", 3), ("node-c", 3), ("node-d", 1)):
                pointer = json.loads(
                    (nodes[node_id]["state"] / "catalog-state.json").read_bytes()
                )
                self.assertEqual(pointer["generation"], expected, node_id)
            audit_lines = (work / "fleet-audit.log").read_text(
                encoding="utf-8").splitlines()
            self.assertEqual(
                [line.split()[1] for line in audit_lines if line.startswith("revert ")],
                ["node-b", "node-a"],
            )
            before_replay = list(audit_lines)
            replay = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-fleet-recover",
                "--plan", str(plan.resolve()), "--expected-plan-sha256",
                self.digest(plan), "--executor-config", str(executor_config.resolve()),
                "--expected-executor-config-sha256", self.digest(executor_config),
                "--state-dir", str(fleet_state.resolve()), environment=environment,
            )
            self.assertEqual(replay.returncode, 2, replay.stdout + replay.stderr)
            self.assertEqual(
                (work / "fleet-audit.log").read_text(encoding="utf-8").splitlines(),
                before_replay,
            )
            collision = work / "fleet-plan-collision.json"
            collision_document = json.loads(plan.read_bytes())
            collision_document["maxParallelNodes"] = 1
            collision.write_text(
                json.dumps(collision_document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            collision_result = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-fleet-recover",
                "--plan", str(collision.resolve()), "--expected-plan-sha256",
                self.digest(collision), "--executor-config",
                str(executor_config.resolve()),
                "--expected-executor-config-sha256", self.digest(executor_config),
                "--state-dir", str(fleet_state.resolve()), environment=environment,
            )
            self.assertEqual(collision_result.returncode, 2)
            collision_status = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-fleet-status",
                "--plan", str(collision.resolve()), "--expected-plan-sha256",
                self.digest(collision), "--state-dir", str(fleet_state.resolve()),
            )
            self.assertEqual(collision_status.returncode, 2)
            original = journal_path.read_bytes()
            tampered = json.loads(original)
            tampered["nodes"][0]["attempts"] += 1
            journal_path.write_text(json.dumps(tampered), encoding="utf-8")
            tamper_result = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-fleet-status",
                "--plan", str(plan.resolve()), "--expected-plan-sha256",
                self.digest(plan), "--state-dir", str(fleet_state.resolve()),
            )
            self.assertEqual(tamper_result.returncode, 2)
            journal_path.write_bytes(original)
            unsafe_plan = work / "unsafe-plan.json"
            unsafe_document = json.loads(plan.read_bytes())
            unsafe_document["rolloutId"] = "unsafe:rollout"
            unsafe_plan.write_text(json.dumps(unsafe_document), encoding="utf-8")
            unsafe_result = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-fleet-status",
                "--plan", str(unsafe_plan.resolve()), "--expected-plan-sha256",
                self.digest(unsafe_plan), "--state-dir", str(fleet_state.resolve()),
            )
            self.assertEqual(unsafe_result.returncode, 2)
        print(
            "PDR_ADAPTER_CATALOG_FLEET_PASS plan=1 executor=1 canary=1 "
            "waves=1 parallel=1 failureBudget=1 pause=1 reverseRollback=1 "
            "nodeReconciler=1 crashRecovery=1 idempotency=1 collision=1 "
            "pendingIsolation=1 journal=1 pins=1 redaction=1 capability=1 cli=1"
        )


if __name__ == "__main__":
    unittest.main()
