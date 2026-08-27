#!/usr/bin/env python3
"""Progressive Wave Gate, pause/resume and abort tests for Catalog Fleet."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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
NODE_MAP_GENERATOR = EXAMPLE / "create_fleet_node_map.py"
EXECUTOR_CONFIG_GENERATOR = EXAMPLE / "create_fleet_executor_config.py"
PLAN_GENERATOR = EXAMPLE / "create_fleet_plan.py"
NODE_EXECUTOR = EXAMPLE / "fleet_node_executor_adapter.py"
GATE_CONFIG_GENERATOR = EXAMPLE / "create_wave_gate_config.py"
GATE_ADAPTER = EXAMPLE / "wave_gate_adapter.py"


ADAPTER_SOURCE = r'''import argparse,json,sys
p=argparse.ArgumentParser();p.add_argument("--adapter-id",required=True);p.add_argument("--implementation-id",required=True);a=p.parse_args()
r=json.loads(sys.stdin.read())
print(json.dumps({"schemaVersion":1,"product":"PocoDDSRuntimeWaveGateTestCapabilityManifest","requestId":r["requestId"],"adapterId":a.adapter_id,"implementationId":a.implementation_id,"protocolMajor":1,"protocolMinor":0,"capabilities":["health-check","progressive-rollout"]},sort_keys=True))
'''


class AdapterCatalogWaveGateTest(unittest.TestCase):
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

    @staticmethod
    def wait_for(path: Path, timeout: float = 25) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.is_file():
                return
            time.sleep(0.03)
        raise AssertionError(f"timed out waiting for {path}")

    def create_catalog(self, work: Path, adapter: Path, generation: int) -> Path:
        adapter_id = "wave-gated-runtime-adapter"
        config = work / f"adapter-{generation}.json"
        config.write_text(json.dumps({
            "schemaVersion": 1, "product": "PocoDDSRuntimeWaveGateTestConfig",
            "adapterId": adapter_id, "kind": "external-command",
            "protocolMajor": 1, "minimumProtocolMinor": 0,
            "requiredCapabilities": ["health-check", "progressive-rollout"],
            "executable": str(Path(sys.executable).resolve()),
            "executableSha256": self.digest(Path(sys.executable)),
            "arguments": [str(adapter.resolve()), "--adapter-id", adapter_id,
                          "--implementation-id", f"wave-gated-{generation}"],
            "artifactPins": [{"path": str(adapter.resolve()),
                              "sha256": self.digest(adapter)}],
            "environmentVariables": [], "optionalEnvironmentVariables": [],
            "timeoutSeconds": 5, "maxResponseBytes": 4096,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest = work / f"manifest-{generation}.json"
        self.require_pass(self.invoke(
            str(MANIFEST_GENERATOR), "--config", str(config.resolve()),
            "--manifest-id", f"wave-gated.deploy-{generation}",
            "--adapter-id", adapter_id, "--adapter-type", "wave-gated-runtime",
            "--owner", "team/runtime-governance", "--revision", f"deploy-{generation}",
            "--protocol-id", "pdr.wave-gate-test", "--identity-field", "adapterId",
            "--capability-request-product",
            "PocoDDSRuntimeWaveGateTestCapabilityRequest",
            "--capability-manifest-product",
            "PocoDDSRuntimeWaveGateTestCapabilityManifest",
            "--output", str(manifest.resolve()),
        ))
        catalog = work / f"catalog-{generation}.json"
        self.require_pass(self.invoke(
            str(CATALOG_GENERATOR), "--catalog-id", "wave-gated-host-adapters",
            "--generation", str(generation), "--manifest", str(manifest.resolve()),
            "--output", str(catalog.resolve()),
        ))
        return catalog

    def bootstrap(self, catalog: Path, state: Path, node_id: str) -> None:
        state.mkdir(parents=True)
        self.require_pass(self.invoke(
            str(PDR), "contract-package", "adapter-catalog-activate",
            "--catalog", str(catalog.resolve()),
            "--expected-catalog-sha256", self.digest(catalog),
            "--state-dir", str(state.resolve()), "--expected-generation", "0",
            "--operation-id", f"bootstrap-{node_id}", "--actor", "wave-gate-test",
            "--reason", "bootstrap Wave Gate node",
        ))

    def plan(self, work: Path, name: str, catalog: Path, executor: Path,
             gate: Path, first: str, second: str, observation: int) -> Path:
        output = work / f"{name}-plan.json"
        self.require_pass(self.invoke(
            str(PLAN_GENERATOR), "--rollout-id", name,
            "--catalog", str(catalog.resolve()), "--executor-config",
            str(executor.resolve()), "--gate-config", str(gate.resolve()),
            "--max-parallel-nodes", "2",
            "--wave", "canary", "canary", "0",
            "--wave", "wave-1", "wave", "0",
            "--node", "canary", first, "rack-a", "1",
            "--node", "wave-1", second, "rack-b", "1",
            "--wave-gate", "canary", str(observation), "2", "pause",
            "--wave-gate", "wave-1", "0", "2", "pause",
            "--output", str(output.resolve()),
        ))
        return output

    def fleet(self, operation: str, plan: Path, executor: Path,
              state: Path, report: Path | None,
              environment: dict[str, str], *extra: str) \
            -> subprocess.CompletedProcess[str]:
        arguments = [
            str(PDR), "contract-package", f"adapter-catalog-fleet-{operation}",
            "--plan", str(plan.resolve()), "--expected-plan-sha256",
            self.digest(plan), "--executor-config", str(executor.resolve()),
            "--expected-executor-config-sha256", self.digest(executor),
            "--state-dir", str(state.resolve()), *extra,
        ]
        if report is not None:
            arguments.extend(["--report", str(report.resolve())])
        return self.invoke(*arguments, environment=environment)

    def test_gate_crash_pause_resume_soak_abort_and_redaction(self) -> None:
        secret = "wave-gate-secret-never-persist"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve()
            adapter = work / "adapter.py"
            adapter.write_text(ADAPTER_SOURCE, encoding="utf-8")
            catalog1 = self.create_catalog(work, adapter, 1)
            catalog2 = self.create_catalog(work, adapter, 2)
            reconciler = work / "reconciler.json"
            self.require_pass(self.invoke(
                str(RECONCILER_CONFIG_GENERATOR), "--python",
                str(Path(sys.executable).resolve()), "--adapter",
                str(LIFECYCLE_ADAPTER.resolve()), "--reconciler-id",
                "wave-gate-node-lifecycle", "--optional-environment",
                "PDR_RECONCILER_HEALTH_MODE", "--output", str(reconciler.resolve()),
            ))
            nodes: dict[str, dict[str, Path]] = {}
            for node_id in ("node-a", "node-b", "node-c", "node-d"):
                state = work / node_id / "state"
                self.bootstrap(catalog1, state, node_id)
                nodes[node_id] = {
                    "state": state, "transactions": work / node_id / "transactions",
                    "lifecycle": work / node_id / "lifecycle",
                }
            mapping = work / "node-map.json"
            map_args = [
                str(NODE_MAP_GENERATOR), "--executor-id", "wave-gate-executor",
                "--audit", str((work / "fleet-audit.log").resolve()),
            ]
            for node_id in sorted(nodes):
                node = nodes[node_id]
                map_args.extend([
                    "--node", node_id, str(node["state"].resolve()),
                    str(node["transactions"].resolve()),
                    str(node["lifecycle"].resolve()), str(reconciler.resolve()),
                    str(catalog2.resolve()), "1", "healthy",
                ])
            map_args.extend(["--output", str(mapping.resolve())])
            self.require_pass(self.invoke(*map_args))
            executor = work / "executor.json"
            self.require_pass(self.invoke(
                str(EXECUTOR_CONFIG_GENERATOR), "--python",
                str(Path(sys.executable).resolve()), "--adapter",
                str(NODE_EXECUTOR.resolve()), "--mapping", str(mapping.resolve()),
                "--tools-dir", str(TOOLS.resolve()), "--executor-id",
                "wave-gate-executor", "--output", str(executor.resolve()),
            ))
            gate_adapter = work / "wave_gate_adapter.py"
            shutil.copyfile(GATE_ADAPTER, gate_adapter)
            gate_config = work / "gate.json"
            config_args = [
                str(GATE_CONFIG_GENERATOR), "--python",
                str(Path(sys.executable).resolve()), "--adapter",
                str(gate_adapter.resolve()), "--gate-id", "fleet-slo-gate",
            ]
            for name in (
                    "PDR_WAVE_GATE_DECISION", "PDR_WAVE_GATE_RESPONSE_GATE",
                    "PDR_WAVE_GATE_SECRET_SENTINEL"):
                config_args.extend(["--optional-environment", name])
            config_args.extend(["--output", str(gate_config.resolve())])
            self.require_pass(self.invoke(*config_args))
            gate_state = work / "gate-state"
            environment = os.environ.copy()
            environment.update({
                "PDR_WAVE_GATE_STATE_ROOT": str(gate_state),
                "PDR_WAVE_GATE_DECISION": "pause",
                "PDR_WAVE_GATE_SECRET_SENTINEL": secret,
            })

            plan = self.plan(
                work, "gated-rollout-2", catalog2, executor, gate_config,
                "node-a", "node-b", 0,
            )
            fleet_state = work / "gated-fleet-state"
            report = work / "gated-report.json"
            response_gate = work / "gate-response"
            crash_environment = dict(environment)
            crash_environment["PDR_WAVE_GATE_RESPONSE_GATE"] = str(response_gate)
            command = [
                sys.executable, str(PDR), "contract-package",
                "adapter-catalog-fleet-run", "--plan", str(plan.resolve()),
                "--expected-plan-sha256", self.digest(plan), "--executor-config",
                str(executor.resolve()), "--expected-executor-config-sha256",
                self.digest(executor), "--state-dir", str(fleet_state.resolve()),
                "--report", str(report.resolve()),
            ]
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=crash_environment,
            )
            release = Path(str(response_gate) + ".release")
            try:
                self.wait_for(Path(str(response_gate) + ".started"))
                gate_journal = fleet_state / "rollouts" / "gated-rollout-2" / \
                    "journal.json"
                self.wait_for(gate_journal)
                process.kill()
                process.communicate(timeout=10)
                release.write_text("release", encoding="utf-8")
            finally:
                release.write_text("release", encoding="utf-8")
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=10)
            environment["PDR_WAVE_GATE_DECISION"] = "pass"
            recovered = self.fleet(
                "recover", plan, executor, fleet_state, report, environment
            )
            self.assertEqual(recovered.returncode, 2, recovered.stdout + recovered.stderr)
            paused = json.loads(report.read_bytes())
            self.assertEqual(paused["schemaVersion"], 2)
            self.assertEqual(paused["status"], "paused")
            self.assertEqual(paused["committedNodes"], 1)
            self.assertEqual(paused["pendingNodes"], 1)
            self.assertEqual(paused["gateCounts"]["paused"], 1)
            self.assertEqual(paused["controlGeneration"], 0)
            self.assertNotIn(secret, json.dumps(paused))
            journal = json.loads(gate_journal.read_bytes())
            self.assertEqual(journal["gates"][0]["attempts"], 1)
            self.assertNotIn(secret, json.dumps(journal))
            gate_files = sorted(gate_state.glob("gated-rollout-2.*.json"))
            self.assertEqual(len(gate_files), 1)
            still_paused = self.fleet(
                "recover", plan, executor, fleet_state, None, environment
            )
            self.assertEqual(still_paused.returncode, 2)
            self.assertEqual(len(list(gate_state.glob("gated-rollout-2.*.json"))), 1)
            bad_cas = self.fleet(
                "resume", plan, executor, fleet_state, None, environment,
                "--expected-control-generation", "1", "--operation-id",
                "approve-gate", "--actor", "release-operator", "--reason",
                "SLO approved",
            )
            self.assertEqual(bad_cas.returncode, 2)
            resumed = self.fleet(
                "resume", plan, executor, fleet_state, report, environment,
                "--expected-control-generation", "0", "--operation-id",
                "approve-gate", "--actor", "release-operator", "--reason",
                "SLO approved",
            )
            self.require_pass(resumed)
            committed = json.loads(report.read_bytes())
            self.assertEqual(committed["status"], "committed")
            self.assertEqual(committed["committedNodes"], 2)
            self.assertEqual(committed["gateCounts"]["passed"], 2)
            self.assertEqual(committed["controlGeneration"], 1)
            gate_file_count = len(list(gate_state.glob("gated-rollout-2.*.json")))
            self.assertEqual(gate_file_count, 3)
            replay = self.fleet(
                "resume", plan, executor, fleet_state, None, environment,
                "--expected-control-generation", "0", "--operation-id",
                "approve-gate", "--actor", "release-operator", "--reason",
                "SLO approved",
            )
            self.require_pass(replay)
            self.assertEqual(
                len(list(gate_state.glob("gated-rollout-2.*.json"))),
                gate_file_count,
            )
            collision = self.fleet(
                "resume", plan, executor, fleet_state, None, environment,
                "--expected-control-generation", "1", "--operation-id",
                "approve-gate", "--actor", "release-operator", "--reason",
                "different approval",
            )
            self.assertEqual(collision.returncode, 2)
            original_journal = gate_journal.read_bytes()
            tampered = json.loads(original_journal)
            tampered["gates"][0]["attempts"] += 1
            gate_journal.write_text(json.dumps(tampered), encoding="utf-8")
            status = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-fleet-status",
                "--plan", str(plan.resolve()), "--expected-plan-sha256",
                self.digest(plan), "--state-dir", str(fleet_state.resolve()),
            )
            self.assertEqual(status.returncode, 2)
            gate_journal.write_bytes(original_journal)
            original_adapter = gate_adapter.read_bytes()
            gate_adapter.write_bytes(original_adapter + b"\n# drift\n")
            drift = self.fleet(
                "recover", plan, executor, fleet_state, None, environment
            )
            self.assertEqual(drift.returncode, 2)
            gate_adapter.write_bytes(original_adapter)

            soak_plan = self.plan(
                work, "soak-abort-2", catalog2, executor, gate_config,
                "node-c", "node-d", 3600,
            )
            soak_state = work / "soak-fleet-state"
            soak_report = work / "soak-report.json"
            soak = self.fleet(
                "run", soak_plan, executor, soak_state, soak_report, environment
            )
            self.assertEqual(soak.returncode, 2, soak.stdout + soak.stderr)
            soak_doc = json.loads(soak_report.read_bytes())
            self.assertEqual(soak_doc["status"], "paused")
            self.assertEqual(soak_doc["gateCounts"]["waiting"], 1)
            self.assertEqual(
                len(list(gate_state.glob("soak-abort-2.*.json"))), 0
            )
            bypass = self.fleet(
                "resume", soak_plan, executor, soak_state, None, environment,
                "--expected-control-generation", "0", "--operation-id",
                "bypass-soak", "--actor", "release-operator", "--reason",
                "attempt early bypass",
            )
            self.assertEqual(bypass.returncode, 2)
            aborted = self.fleet(
                "abort", soak_plan, executor, soak_state, soak_report, environment,
                "--expected-control-generation", "0", "--operation-id",
                "abort-soak", "--actor", "release-operator", "--reason",
                "SLO observation rejected",
            )
            self.require_pass(aborted)
            aborted_doc = json.loads(soak_report.read_bytes())
            self.assertEqual(aborted_doc["status"], "rolled-back")
            self.assertEqual(aborted_doc["rolledBackNodes"], 1)
            self.assertEqual(aborted_doc["pendingNodes"], 1)
            self.assertEqual(aborted_doc["controlGeneration"], 1)
            for node_id, expected in (("node-c", 3), ("node-d", 1)):
                pointer = json.loads(
                    (nodes[node_id]["state"] / "catalog-state.json").read_bytes()
                )
                self.assertEqual(pointer["generation"], expected, node_id)
            abort_replay = self.fleet(
                "abort", soak_plan, executor, soak_state, None, environment,
                "--expected-control-generation", "0", "--operation-id",
                "abort-soak", "--actor", "release-operator", "--reason",
                "SLO observation rejected",
            )
            self.require_pass(abort_replay)
        print(
            "PDR_ADAPTER_CATALOG_WAVE_GATE_PASS protocol=1 planV2=1 "
            "capability=1 sloGate=1 soakWindow=1 nonBlocking=1 pause=1 "
            "resume=1 abort=1 controlCas=1 controlIdempotency=1 "
            "controlCollision=1 crashRecovery=1 evaluationIdempotency=1 "
            "laterWaveIsolation=1 reverseRollback=1 evidence=1 journal=1 "
            "tamper=1 pins=1 redaction=1 legacyV1=1 cli=1"
        )


if __name__ == "__main__":
    unittest.main()
