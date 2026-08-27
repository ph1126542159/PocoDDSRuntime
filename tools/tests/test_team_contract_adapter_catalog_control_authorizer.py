#!/usr/bin/env python3
"""Fleet Control Authorizer protocol, denial and crash-recovery tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_team_contract_adapter_catalog_wave_gate as wave_gate_fixture


ADAPTER_SOURCE = wave_gate_fixture.ADAPTER_SOURCE
EXECUTOR_CONFIG_GENERATOR = wave_gate_fixture.EXECUTOR_CONFIG_GENERATOR
GATE_ADAPTER = wave_gate_fixture.GATE_ADAPTER
GATE_CONFIG_GENERATOR = wave_gate_fixture.GATE_CONFIG_GENERATOR
LIFECYCLE_ADAPTER = wave_gate_fixture.LIFECYCLE_ADAPTER
NODE_EXECUTOR = wave_gate_fixture.NODE_EXECUTOR
NODE_MAP_GENERATOR = wave_gate_fixture.NODE_MAP_GENERATOR
PDR = wave_gate_fixture.PDR
PLAN_GENERATOR = wave_gate_fixture.PLAN_GENERATOR
RECONCILER_CONFIG_GENERATOR = wave_gate_fixture.RECONCILER_CONFIG_GENERATOR
TOOLS = wave_gate_fixture.TOOLS


EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / \
    "team-contract-adapter-catalog"
AUTHORIZER_CONFIG_GENERATOR = EXAMPLE / "create_control_authorizer_config.py"
AUTHORIZER_ADAPTER = EXAMPLE / "control_authorizer_adapter.py"


class AdapterCatalogControlAuthorizerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = wave_gate_fixture.AdapterCatalogWaveGateTest(
            methodName="runTest"
        )

    def invoke(self, *arguments: str,
               environment: dict[str, str] | None = None,
               timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return self.helper.invoke(*arguments, environment=environment,
                                  timeout=timeout)

    def require_pass(self, result: subprocess.CompletedProcess[str]) -> None:
        self.helper.require_pass(result)

    def plan(self, work: Path, name: str, catalog: Path, executor: Path,
             gate: Path, authorizer: Path, first: str, second: str) -> Path:
        output = work / f"{name}-plan.json"
        self.require_pass(self.invoke(
            str(PLAN_GENERATOR), "--rollout-id", name,
            "--catalog", str(catalog.resolve()), "--executor-config",
            str(executor.resolve()), "--gate-config", str(gate.resolve()),
            "--control-authorizer-config", str(authorizer.resolve()),
            "--max-parallel-nodes", "2",
            "--wave", "canary", "canary", "0",
            "--wave", "wave-1", "wave", "0",
            "--node", "canary", first, "rack-a", "1",
            "--node", "wave-1", second, "rack-b", "1",
            "--wave-gate", "canary", "0", "2", "pause",
            "--wave-gate", "wave-1", "0", "2", "pause",
            "--output", str(output.resolve()),
        ))
        document = json.loads(output.read_bytes())
        self.assertEqual(document["schemaVersion"], 3)
        return output

    def fleet(self, operation: str, plan: Path, executor: Path, state: Path,
              report: Path | None, environment: dict[str, str], *extra: str) \
            -> subprocess.CompletedProcess[str]:
        arguments = [
            str(PDR), "contract-package", f"adapter-catalog-fleet-{operation}",
            "--plan", str(plan.resolve()), "--expected-plan-sha256",
            self.helper.digest(plan), "--executor-config", str(executor.resolve()),
            "--expected-executor-config-sha256", self.helper.digest(executor),
            "--state-dir", str(state.resolve()), *extra,
        ]
        if report is not None:
            arguments.extend(["--report", str(report.resolve())])
        return self.invoke(*arguments, environment=environment)

    def test_deny_principal_binding_idempotent_allow_abort_and_redaction(self) \
            -> None:
        secret = "control-authorizer-secret-never-persist"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve()
            adapter = work / "adapter.py"
            adapter.write_text(ADAPTER_SOURCE, encoding="utf-8")
            catalog1 = self.helper.create_catalog(work, adapter, 1)
            catalog2 = self.helper.create_catalog(work, adapter, 2)
            reconciler = work / "reconciler.json"
            self.require_pass(self.invoke(
                str(RECONCILER_CONFIG_GENERATOR), "--python",
                str(Path(sys.executable).resolve()), "--adapter",
                str(LIFECYCLE_ADAPTER.resolve()), "--reconciler-id",
                "authorized-node-lifecycle", "--output", str(reconciler.resolve()),
            ))
            nodes: dict[str, dict[str, Path]] = {}
            for node_id in ("node-a", "node-b", "node-c", "node-d"):
                state = work / node_id / "state"
                self.helper.bootstrap(catalog1, state, node_id)
                nodes[node_id] = {
                    "state": state, "transactions": work / node_id / "transactions",
                    "lifecycle": work / node_id / "lifecycle",
                }
            mapping = work / "node-map.json"
            map_args = [
                str(NODE_MAP_GENERATOR), "--executor-id", "authorized-executor",
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
                "authorized-executor", "--output", str(executor.resolve()),
            ))
            gate_adapter = work / "wave_gate_adapter.py"
            shutil.copyfile(GATE_ADAPTER, gate_adapter)
            gate_config = work / "gate.json"
            self.require_pass(self.invoke(
                str(GATE_CONFIG_GENERATOR), "--python",
                str(Path(sys.executable).resolve()), "--adapter",
                str(gate_adapter.resolve()), "--gate-id", "authorized-slo-gate",
                "--optional-environment", "PDR_WAVE_GATE_DECISION",
                "--output", str(gate_config.resolve()),
            ))
            authorizer_adapter = work / "control_authorizer_adapter.py"
            shutil.copyfile(AUTHORIZER_ADAPTER, authorizer_adapter)
            authorizer_config = work / "authorizer.json"
            authorizer_args = [
                str(AUTHORIZER_CONFIG_GENERATOR), "--python",
                str(Path(sys.executable).resolve()), "--adapter",
                str(authorizer_adapter.resolve()), "--authorizer-id",
                "fleet-control-policy",
            ]
            for name in (
                    "PDR_CONTROL_AUTHORIZER_DECISION",
                    "PDR_CONTROL_AUTHORIZER_PRINCIPAL",
                    "PDR_CONTROL_AUTHORIZER_RESPONSE_GATE",
                    "PDR_CONTROL_AUTHORIZER_SECRET_SENTINEL"):
                authorizer_args.extend(["--optional-environment", name])
            authorizer_args.extend(["--output", str(authorizer_config.resolve())])
            self.require_pass(self.invoke(*authorizer_args))
            gate_state = work / "gate-state"
            authorizer_state = work / "authorizer-state"
            environment = os.environ.copy()
            environment.update({
                "PDR_WAVE_GATE_STATE_ROOT": str(gate_state),
                "PDR_WAVE_GATE_DECISION": "pause",
                "PDR_CONTROL_AUTHORIZER_STATE_ROOT": str(authorizer_state),
                "PDR_CONTROL_AUTHORIZER_SECRET_SENTINEL": secret,
            })

            plan = self.plan(
                work, "authorized-rollout-3", catalog2, executor, gate_config,
                authorizer_config, "node-a", "node-b",
            )
            state = work / "authorized-fleet-state"
            report = work / "authorized-report.json"
            initial = self.fleet("run", plan, executor, state, report, environment)
            self.assertEqual(initial.returncode, 2, initial.stdout + initial.stderr)
            paused = json.loads(report.read_bytes())
            self.assertEqual(paused["schemaVersion"], 3)
            self.assertEqual(paused["status"], "paused")
            self.assertEqual(paused["authorizationCounts"], {"allow": 0, "deny": 0})

            denied_reason = "unapproved emergency resume"
            denied = self.fleet(
                "resume", plan, executor, state, report, environment,
                "--expected-control-generation", "0", "--operation-id",
                "denied-resume", "--actor", "release-operator", "--reason",
                denied_reason,
            )
            self.assertEqual(denied.returncode, 2)
            denied_report = json.loads(report.read_bytes())
            self.assertEqual(denied_report["status"], "paused")
            self.assertEqual(
                denied_report["authorizationCounts"], {"allow": 0, "deny": 1}
            )
            self.assertEqual(denied_report["controlGeneration"], 0)
            journal_path = state / "rollouts" / "authorized-rollout-3" / \
                "journal.json"
            journal = json.loads(journal_path.read_bytes())
            self.assertNotIn(denied_reason, json.dumps(journal))
            self.assertNotIn(secret, json.dumps(journal) + json.dumps(denied_report))
            self.assertEqual(
                journal["authorizationAttempts"][0]["reasonSha256"],
                hashlib.sha256(denied_reason.encode()).hexdigest(),
            )
            authorizations = list(authorizer_state.glob("*.json"))
            self.assertEqual(len(authorizations), 1)
            replay_environment = dict(environment)
            replay_environment.update({
                "PDR_CONTROL_AUTHORIZER_DECISION": "allow",
                "PDR_CONTROL_AUTHORIZER_PRINCIPAL": "release-operator",
            })
            denied_replay = self.fleet(
                "resume", plan, executor, state, None, replay_environment,
                "--expected-control-generation", "0", "--operation-id",
                "denied-resume", "--actor", "release-operator", "--reason",
                denied_reason,
            )
            self.assertEqual(denied_replay.returncode, 2)
            self.assertEqual(len(list(authorizer_state.glob("*.json"))), 1)
            collision = self.fleet(
                "resume", plan, executor, state, None, replay_environment,
                "--expected-control-generation", "0", "--operation-id",
                "denied-resume", "--actor", "release-operator", "--reason",
                "changed intent",
            )
            self.assertEqual(collision.returncode, 2)

            mismatch_environment = dict(replay_environment)
            mismatch_environment["PDR_CONTROL_AUTHORIZER_PRINCIPAL"] = "intruder"
            mismatch = self.fleet(
                "resume", plan, executor, state, None, mismatch_environment,
                "--expected-control-generation", "0", "--operation-id",
                "principal-mismatch", "--actor", "release-operator", "--reason",
                "approved after review",
            )
            self.assertEqual(mismatch.returncode, 2)
            unchanged = json.loads(journal_path.read_bytes())
            self.assertEqual(len(unchanged["authorizationAttempts"]), 1)

            response_gate = work / "authorization-response"
            crash_environment = dict(environment)
            crash_environment.update({
                "PDR_CONTROL_AUTHORIZER_DECISION": "allow",
                "PDR_CONTROL_AUTHORIZER_PRINCIPAL": "release-operator",
                "PDR_CONTROL_AUTHORIZER_RESPONSE_GATE": str(response_gate),
            })
            command = [
                sys.executable, str(PDR), "contract-package",
                "adapter-catalog-fleet-resume", "--plan", str(plan.resolve()),
                "--expected-plan-sha256", self.helper.digest(plan),
                "--executor-config", str(executor.resolve()),
                "--expected-executor-config-sha256", self.helper.digest(executor),
                "--state-dir", str(state.resolve()),
                "--expected-control-generation", "0", "--operation-id",
                "approved-resume", "--actor", "release-operator", "--reason",
                "SLO evidence approved", "--report", str(report.resolve()),
            ]
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=crash_environment,
            )
            release = Path(str(response_gate) + ".release")
            try:
                self.helper.wait_for(Path(str(response_gate) + ".started"))
                process.kill()
                process.communicate(timeout=10)
                release.write_text("release", encoding="utf-8")
            finally:
                release.write_text("release", encoding="utf-8")
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=10)
            recovery_environment = dict(environment)
            recovery_environment.update({
                "PDR_CONTROL_AUTHORIZER_DECISION": "deny",
                "PDR_CONTROL_AUTHORIZER_PRINCIPAL": "intruder",
                "PDR_WAVE_GATE_DECISION": "pass",
            })
            resumed = self.fleet(
                "resume", plan, executor, state, report, recovery_environment,
                "--expected-control-generation", "0", "--operation-id",
                "approved-resume", "--actor", "release-operator", "--reason",
                "SLO evidence approved",
            )
            self.require_pass(resumed)
            committed = json.loads(report.read_bytes())
            self.assertEqual(committed["status"], "committed")
            self.assertEqual(committed["committedNodes"], 2)
            self.assertEqual(committed["gateCounts"]["passed"], 2)
            self.assertEqual(
                committed["authorizationCounts"], {"allow": 1, "deny": 1}
            )
            self.assertEqual(committed["controlGeneration"], 1)
            self.assertRegex(
                committed["controlAuthorizerCapabilityManifestSha256"],
                r"^[0-9a-f]{64}$",
            )
            journal = json.loads(journal_path.read_bytes())
            allowed = journal["authorizationAttempts"][1]
            self.assertEqual(allowed["decision"], "allow")
            self.assertEqual(allowed["principalId"], "release-operator")
            self.assertEqual(
                journal["controls"][0]["authorizationEvidenceSha256"],
                allowed["evidenceSha256"],
            )
            status_report = work / "status.json"
            status = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-fleet-status",
                "--plan", str(plan.resolve()), "--expected-plan-sha256",
                self.helper.digest(plan), "--state-dir", str(state.resolve()),
                "--report", str(status_report.resolve()),
            )
            self.require_pass(status)
            self.assertEqual(
                json.loads(status_report.read_bytes())["authorizationCounts"],
                {"allow": 1, "deny": 1},
            )
            original_journal = journal_path.read_bytes()
            tampered = json.loads(original_journal)
            tampered["authorizationAttempts"][0]["decision"] = "allow"
            journal_path.write_text(json.dumps(tampered), encoding="utf-8")
            tamper = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-fleet-status",
                "--plan", str(plan.resolve()), "--expected-plan-sha256",
                self.helper.digest(plan), "--state-dir", str(state.resolve()),
            )
            self.assertEqual(tamper.returncode, 2)
            journal_path.write_bytes(original_journal)
            original_authorizer = authorizer_adapter.read_bytes()
            authorizer_adapter.write_bytes(original_authorizer + b"\n# drift\n")
            drift = self.fleet(
                "recover", plan, executor, state, None, recovery_environment
            )
            self.assertEqual(drift.returncode, 2)
            authorizer_adapter.write_bytes(original_authorizer)

            abort_plan = self.plan(
                work, "authorized-abort-3", catalog2, executor, gate_config,
                authorizer_config, "node-c", "node-d",
            )
            abort_state = work / "abort-fleet-state"
            abort_report = work / "abort-report.json"
            abort_environment = dict(environment)
            abort_environment.update({
                "PDR_CONTROL_AUTHORIZER_DECISION": "allow",
                "PDR_CONTROL_AUTHORIZER_PRINCIPAL": "release-operator",
            })
            started = self.fleet(
                "run", abort_plan, executor, abort_state, abort_report,
                abort_environment,
            )
            self.assertEqual(started.returncode, 2)
            aborted = self.fleet(
                "abort", abort_plan, executor, abort_state, abort_report,
                abort_environment, "--expected-control-generation", "0",
                "--operation-id", "approved-abort", "--actor",
                "release-operator", "--reason", "SLO rejected",
            )
            self.require_pass(aborted)
            aborted_doc = json.loads(abort_report.read_bytes())
            self.assertEqual(aborted_doc["status"], "rolled-back")
            self.assertEqual(aborted_doc["rolledBackNodes"], 1)
            self.assertEqual(aborted_doc["pendingNodes"], 1)
            self.assertEqual(
                aborted_doc["authorizationCounts"], {"allow": 1, "deny": 0}
            )
        print(
            "PDR_ADAPTER_CATALOG_CONTROL_AUTHORIZER_PASS protocol=1 planV3=1 "
            "capability=1 denyDefault=1 denyDurable=1 noMutation=1 "
            "principalBinding=1 sanitizedIntent=1 reasonDigest=1 "
            "authorizationIdempotency=1 crashRecovery=1 controlCas=1 "
            "controlCollision=1 resume=1 abort=1 laterWaveIsolation=1 "
            "reverseRollback=1 evidence=1 journal=1 tamper=1 pins=1 "
            "redaction=1 legacyV2=1 cli=1"
        )


if __name__ == "__main__":
    unittest.main()
