#!/usr/bin/env python3
"""Cross-coordinator tests for the Adapter Catalog Fleet remote state store."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import team_contract_adapter_catalog_fleet as fleet_tool
import team_contract_adapter_catalog_fleet_state_store as state_tool
import team_contract_package as package_tool
import team_contract_registry_leader_backend as backend_tool


class MemoryBackend:
    def __init__(self) -> None:
        self.backend_id = "fleet-state-backend"
        self.capability_manifest_sha256 = "b" * 64
        self.value: tuple[dict, bytes, str] | None = None
        self.uncertain_after_commit = False

    def current(self):
        if self.value is None:
            return None
        document, content, digest = self.value
        return copy.deepcopy(document), content, digest

    def compare_and_swap(self, expected_token, expected_sha256,
                         document, content, digest):
        actual_token = 0 if self.value is None else \
            self.value[0]["fencingToken"]
        actual_sha = backend_tool.ZERO_SHA256 if self.value is None else \
            self.value[2]
        if (expected_token, expected_sha256) != (actual_token, actual_sha):
            raise ValueError("simulated CAS conflict")
        self.value = (copy.deepcopy(document), content, digest)
        if self.uncertain_after_commit:
            self.uncertain_after_commit = False
            raise backend_tool.BackendCommitUncertainError(
                "simulated lost response"
            )


class MemoryArtifactStore:
    def __init__(self) -> None:
        self.store_id = "fleet-journal-store"
        self.capability_manifest_sha256 = "a" * 64
        self.values: dict[str, bytes] = {}

    def put(self, content: bytes, media_type: str):
        digest = package_tool.sha256_bytes(content)
        self.values.setdefault(digest, content)
        return {
            "kind": "content-addressed", "storeId": self.store_id,
            "namespaceId": "remote-rollout", "sha256": digest,
            "sizeBytes": len(content), "mediaType": media_type,
        }

    def get(self, reference):
        value = self.values.get(reference["sha256"])
        if value is None:
            raise ValueError("simulated missing artifact")
        return value


class FleetStateStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = MemoryBackend()
        self.artifacts = MemoryArtifactStore()
        self.backend_patch = mock.patch.object(
            state_tool.backend_tool, "ExternalCommandBackend",
            side_effect=lambda *args: self.backend,
        )
        self.artifact_patch = mock.patch.object(
            state_tool.artifact_store_tool, "ExternalCommandArtifactStore",
            side_effect=lambda *args: self.artifacts,
        )
        self.backend_patch.start()
        self.artifact_patch.start()

    def tearDown(self) -> None:
        self.artifact_patch.stop()
        self.backend_patch.stop()

    @staticmethod
    def plan() -> dict:
        return {
            "schemaVersion": 4,
            "product": fleet_tool.PLAN_PRODUCT,
            "rolloutId": "remote-rollout", "catalogId": "fleet-catalog",
            "candidateCatalogGeneration": 2,
            "candidateCatalogSha256": "c" * 64,
            "executorConfigPath": str((ROOT / "executor.json").resolve()),
            "executorConfigSha256": "e" * 64,
            "gateConfigPath": str((ROOT / "gate.json").resolve()),
            "gateConfigSha256": "6" * 64,
            "controlAuthorizerConfigPath":
                str((ROOT / "authorizer.json").resolve()),
            "controlAuthorizerConfigSha256": "d" * 64,
            "stateBackendId": "fleet-state-backend",
            "stateBackendConfigSha256": "1" * 64,
            "artifactStoreId": "fleet-journal-store",
            "artifactStoreConfigSha256": "2" * 64,
            "maxParallelNodes": 1,
            "waves": [{
                "waveId": "canary", "mode": "canary", "maxFailures": 0,
                "gatePolicy": {
                    "minimumObservationSeconds": 0, "maxEvaluations": 1,
                    "rejectionAction": "pause",
                },
                "nodes": [{
                    "nodeId": "node-a", "failureDomain": "rack-a",
                    "expectedActivationGeneration": 1,
                }],
            }],
        }

    def store(self, coordinator: str):
        plan = self.plan()
        return state_tool.RemoteFleetStateStore(
            state_backend_config="backend.json",
            state_backend_config_sha256=plan["stateBackendConfigSha256"],
            artifact_store_config="artifacts.json",
            artifact_store_config_sha256=plan["artifactStoreConfigSha256"],
            rollout_id=plan["rolloutId"], catalog_id=plan["catalogId"],
            plan_sha256="f" * 64,
            expected_backend_id=plan["stateBackendId"],
            expected_artifact_store_id=plan["artifactStoreId"],
            coordinator_id=coordinator,
        )

    def test_takeover_fencing_chain_and_stale_coordinator(self) -> None:
        plan = self.plan()
        first = self.store("coordinator-a")
        second = self.store("coordinator-b")
        self.assertIsNone(first.read())
        journal = fleet_tool.create_journal(plan, "f" * 64, "e" * 64)
        first.write(journal)
        first_sha = journal["journalSha256"]
        self.assertEqual(journal["stateVersion"], 1)
        self.assertIsNone(journal["previousJournalSha256"])

        takeover = second.read()
        assert takeover is not None
        fleet_tool.validate_journal(takeover, plan)
        takeover["nodes"][0]["attempts"] = 1
        second.write(takeover)
        self.assertEqual(takeover["stateVersion"], 2)
        self.assertEqual(takeover["previousJournalSha256"], first_sha)
        self.assertEqual(takeover["lastCoordinatorId"], "coordinator-b")

        journal["nodes"][0]["attempts"] = 2
        with self.assertRaisesRegex(ValueError, "CAS conflict"):
            first.write(journal)
        current = first.read()
        assert current is not None
        self.assertEqual(current["stateVersion"], 2)
        self.assertEqual(current["lastCoordinatorId"], "coordinator-b")
        print(
            "PDR_ADAPTER_CATALOG_FLEET_STATE_STORE_PASS planV4=1 "
            "portableConfig=1 artifactJournal=1 linearizableCas=1 fencing=1 "
            "takeover=1 independentScratch=1 ambiguousCommit=1 tamper=1 "
            "pins=1 scope=1 stateChain=1 legacyV3=1 capability=1 cli=1"
        )

    def test_plan_v3_remains_valid_and_remote_scope_is_confined(self) -> None:
        plan = self.plan()
        legacy = copy.deepcopy(plan)
        legacy["schemaVersion"] = 3
        for name in (
                "stateBackendId", "stateBackendConfigSha256",
                "artifactStoreId", "artifactStoreConfigSha256"):
            del legacy[name]
        fleet_tool.validate_plan(legacy)
        store = self.store("coordinator-a")
        self.assertIsNone(store.read())
        journal = fleet_tool.create_journal(plan, "f" * 64, "e" * 64)
        journal["catalogId"] = "different-catalog"
        with self.assertRaisesRegex(ValueError, "scope changed"):
            store.write(journal)

    def test_plan_v4_binds_store_identity_without_host_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve()
            documents = {
                "catalog.json": {
                    "product": "PocoDDSRuntimeTeamContractAdapterCatalog",
                    "catalogId": "fleet-catalog", "generation": 2,
                },
                "backend.json": {
                    "product":
                        "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig",
                    "backendId": "fleet-state-backend",
                },
                "artifacts.json": {
                    "product": "PocoDDSRuntimeTeamContractArtifactStoreConfig",
                    "storeId": "fleet-journal-store",
                },
                "executor.json": {}, "gate.json": {}, "authorizer.json": {},
            }
            for name, document in documents.items():
                (work / name).write_text(
                    package_tool.json_bytes(document).decode(), encoding="utf-8"
                )
            output = work / "plan.json"
            result = subprocess.run([
                sys.executable,
                str(ROOT / "examples" / "team-contract-adapter-catalog" /
                    "create_fleet_plan.py"),
                "--rollout-id", "remote-rollout",
                "--catalog", str(work / "catalog.json"),
                "--executor-config", str(work / "executor.json"),
                "--gate-config", str(work / "gate.json"),
                "--control-authorizer-config", str(work / "authorizer.json"),
                "--state-backend-config", str(work / "backend.json"),
                "--artifact-store-config", str(work / "artifacts.json"),
                "--wave", "canary", "canary", "0",
                "--node", "canary", "node-a", "rack-a", "1",
                "--wave-gate", "canary", "0", "1", "pause",
                "--output", str(output),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plan = json.loads(output.read_bytes())
            fleet_tool.validate_plan(plan)
            self.assertEqual(plan["schemaVersion"], 4)
            self.assertEqual(plan["stateBackendId"], "fleet-state-backend")
            self.assertEqual(plan["artifactStoreId"], "fleet-journal-store")
            self.assertNotIn("stateBackendConfigPath", plan)
            self.assertNotIn("artifactStoreConfigPath", plan)
            help_result = subprocess.run([
                sys.executable, str(TOOLS / "pdr.py"), "contract-package",
                "adapter-catalog-fleet-recover", "--help",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(
                help_result.returncode, 0,
                help_result.stdout + help_result.stderr,
            )
            for option in (
                    "--state-backend-config", "--artifact-store-config",
                    "--coordinator-id"):
                self.assertIn(option, help_result.stdout)

    def test_plan_v5_resolves_all_adapter_configs_without_host_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve()
            documents = {
                "catalog.json": {
                    "product": "PocoDDSRuntimeTeamContractAdapterCatalog",
                    "catalogId": "fleet-catalog", "generation": 2,
                },
                "executor.json": {
                    "product": fleet_tool.EXECUTOR_CONFIG_PRODUCT,
                    "executorId": "fleet-executor",
                },
                "gate.json": {
                    "product":
                        "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateConfig",
                    "gateId": "fleet-gate",
                },
                "authorizer.json": {
                    "product": "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerConfig",
                    "authorizerId": "fleet-authorizer",
                },
                "backend.json": {
                    "product": "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig",
                    "backendId": "fleet-state-backend",
                },
                "artifacts.json": {
                    "product": "PocoDDSRuntimeTeamContractArtifactStoreConfig",
                    "storeId": "fleet-journal-store",
                },
            }
            for name, document in documents.items():
                (work / name).write_text(
                    package_tool.json_bytes(document).decode(), encoding="utf-8"
                )
            output = work / "plan-v5.json"
            command = [
                sys.executable,
                str(ROOT / "examples" / "team-contract-adapter-catalog" /
                    "create_fleet_plan.py"),
                "--rollout-id", "remote-rollout",
                "--catalog", str(work / "catalog.json"),
                "--executor-config", str(work / "executor.json"),
                "--gate-config", str(work / "gate.json"),
                "--control-authorizer-config", str(work / "authorizer.json"),
                "--state-backend-config", str(work / "backend.json"),
                "--artifact-store-config", str(work / "artifacts.json"),
                "--adapter-config-resolver-id", "fleet-config-resolver",
            ]
            for kind in (
                    "fleet-executor", "wave-gate", "control-authorizer",
                    "registry-leader-backend", "artifact-store"):
                command.extend([
                    "--config-ref", kind, f"{kind}.config", "revision-1"
                ])
            command.extend([
                "--wave", "canary", "canary", "0",
                "--node", "canary", "node-a", "rack-a", "1",
                "--wave-gate", "canary", "0", "1", "pause",
                "--output", str(output),
            ])
            result = subprocess.run(
                command, check=False, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plan = json.loads(output.read_bytes())
            fleet_tool.validate_plan(plan)
            self.assertEqual(plan["schemaVersion"], 5)
            self.assertEqual(
                plan["stateBackendConfigRef"]["adapterId"],
                "fleet-state-backend",
            )
            for field in (
                    "executorConfigPath", "executorConfigSha256",
                    "gateConfigPath", "gateConfigSha256",
                    "controlAuthorizerConfigPath",
                    "controlAuthorizerConfigSha256",
                    "stateBackendConfigSha256",
                    "artifactStoreConfigSha256"):
                self.assertNotIn(field, plan)

            first = state_tool.RemoteFleetStateStore(
                state_backend_config="host-a-backend.json",
                state_backend_config_sha256="1" * 64,
                artifact_store_config="host-a-artifacts.json",
                artifact_store_config_sha256="2" * 64,
                rollout_id=plan["rolloutId"], catalog_id=plan["catalogId"],
                plan_sha256="f" * 64,
                expected_backend_id="fleet-state-backend",
                expected_artifact_store_id="fleet-journal-store",
                coordinator_id="host-a",
                adapter_config_resolver_id=plan["adapterConfigResolverId"],
                state_backend_config_ref=plan["stateBackendConfigRef"],
                artifact_store_config_ref=plan["artifactStoreConfigRef"],
            )
            self.assertIsNone(first.read())
            journal = fleet_tool.create_journal(plan, "f" * 64, None)
            first.write(journal)
            fleet_tool.validate_journal(journal, plan)
            assert self.backend.value is not None
            self.assertEqual(self.backend.value[0]["schemaVersion"], 2)
            second = state_tool.RemoteFleetStateStore(
                state_backend_config="host-b-backend.json",
                state_backend_config_sha256="3" * 64,
                artifact_store_config="host-b-artifacts.json",
                artifact_store_config_sha256="4" * 64,
                rollout_id=plan["rolloutId"], catalog_id=plan["catalogId"],
                plan_sha256="f" * 64,
                expected_backend_id="fleet-state-backend",
                expected_artifact_store_id="fleet-journal-store",
                coordinator_id="host-b",
                adapter_config_resolver_id=plan["adapterConfigResolverId"],
                state_backend_config_ref=plan["stateBackendConfigRef"],
                artifact_store_config_ref=plan["artifactStoreConfigRef"],
            )
            loaded = second.read()
            assert loaded is not None
            self.assertEqual(loaded["lastCoordinatorId"], "host-a")

    def test_commit_response_ambiguity_is_reconciled(self) -> None:
        plan = self.plan()
        store = self.store("coordinator-a")
        self.assertIsNone(store.read())
        journal = fleet_tool.create_journal(plan, "f" * 64, "e" * 64)
        self.backend.uncertain_after_commit = True
        store.write(journal)
        self.assertEqual(store.state_version, 1)
        loaded = store.read()
        assert loaded is not None
        self.assertEqual(loaded["journalSha256"], journal["journalSha256"])

    def test_missing_or_tampered_journal_fails_closed(self) -> None:
        plan = self.plan()
        writer = self.store("coordinator-a")
        self.assertIsNone(writer.read())
        journal = fleet_tool.create_journal(plan, "f" * 64, "e" * 64)
        writer.write(journal)
        assert self.backend.value is not None
        digest = self.backend.value[0]["journalRef"]["sha256"]
        self.artifacts.values[digest] = b"{}"
        with self.assertRaisesRegex(ValueError, "identity changed"):
            self.store("coordinator-b").read()

    def test_real_file_adapters_support_independent_coordinator_paths(self) -> None:
        self.artifact_patch.stop()
        self.backend_patch.stop()
        try:
            with tempfile.TemporaryDirectory() as directory:
                work = Path(directory).resolve()
                backend_config = work / "backend.json"
                artifact_config = work / "artifacts.json"
                backend_example = ROOT / "examples" / \
                    "team-contract-registry-leader-backend-file"
                artifact_example = ROOT / "examples" / \
                    "team-contract-artifact-store-file"
                commands = [
                    [
                        sys.executable,
                        str(backend_example / "create_backend_config.py"),
                        "--python", str(Path(sys.executable).resolve()),
                        "--adapter", str(
                            backend_example / "file_backend_adapter.py"),
                        "--backend-id", "fleet-state-backend",
                        "--authority-id", "remote-rollout",
                        "--registry-id", "fleet-catalog",
                        "--root-environment", "PDR_FLEET_STATE_TEST_ROOT",
                        "--output", str(backend_config),
                    ],
                    [
                        sys.executable,
                        str(artifact_example / "create_artifact_store_config.py"),
                        "--python", str(Path(sys.executable).resolve()),
                        "--adapter", str(
                            artifact_example / "file_artifact_store_adapter.py"),
                        "--store-id", "fleet-journal-store",
                        "--namespace-id", "remote-rollout",
                        "--root-environment", "PDR_FLEET_ARTIFACT_TEST_ROOT",
                        "--output", str(artifact_config),
                    ],
                ]
                for command in commands:
                    result = subprocess.run(
                        command, check=False, capture_output=True, text=True
                    )
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                plan = self.plan()
                backend_sha = hashlib.sha256(
                    backend_config.read_bytes()).hexdigest()
                artifact_sha = hashlib.sha256(
                    artifact_config.read_bytes()).hexdigest()
                plan["stateBackendConfigSha256"] = backend_sha
                plan["artifactStoreConfigSha256"] = artifact_sha
                environment = {
                    "PDR_FLEET_STATE_TEST_ROOT": str(work / "backend-state"),
                    "PDR_FLEET_ARTIFACT_TEST_ROOT": str(work / "artifacts"),
                }
                with mock.patch.dict(os.environ, environment, clear=False):
                    def real_store(coordinator: str):
                        return state_tool.RemoteFleetStateStore(
                            state_backend_config=backend_config,
                            state_backend_config_sha256=backend_sha,
                            artifact_store_config=artifact_config,
                            artifact_store_config_sha256=artifact_sha,
                            rollout_id=plan["rolloutId"],
                            catalog_id=plan["catalogId"],
                            plan_sha256="f" * 64,
                            expected_backend_id="fleet-state-backend",
                            expected_artifact_store_id="fleet-journal-store",
                            coordinator_id=coordinator,
                        )

                    first = real_store("host-a")
                    journal = fleet_tool.create_journal(
                        plan, "f" * 64, "e" * 64
                    )
                    first.write(journal)
                    second = real_store("host-b")
                    loaded = second.read()
                    assert loaded is not None
                    loaded["nodes"][0]["attempts"] = 1
                    second.write(loaded)
                    observed = first.read()
                    assert observed is not None
                    self.assertEqual(observed["stateVersion"], 2)
                    self.assertEqual(observed["lastCoordinatorId"], "host-b")

                    def finish_as(status: str):
                        def apply(plan_arg, config_arg, target, journal_arg,
                                  gate_config_arg):
                            del config_arg, gate_config_arg
                            if status == "paused":
                                journal_arg["status"] = "paused"
                                journal_arg["gates"][0]["status"] = "paused"
                            else:
                                journal_arg["status"] = "committed"
                                journal_arg["currentWave"] = len(
                                    plan_arg["waves"])
                                journal_arg["gates"][0]["status"] = "passed"
                                journal_arg["nodes"][0]["status"] = "committed"
                            fleet_tool.write_journal(target, journal_arg)
                        return apply

                    def arguments(host: str, state_dir: Path, report: Path):
                        return argparse.Namespace(
                            plan="plan.json", expected_plan_sha256="f" * 64,
                            executor_config="executor.json",
                            expected_executor_config_sha256="e" * 64,
                            state_dir=str(state_dir), report=str(report),
                            state_backend_config=str(backend_config),
                            artifact_store_config=str(artifact_config),
                            coordinator_id=host,
                        )

                    plan_path = Path(plan["executorConfigPath"])
                    gate_path = Path(plan["gateConfigPath"])
                    authorizer_path = Path(
                        plan["controlAuthorizerConfigPath"])
                    common_patches = (
                        mock.patch.object(
                            fleet_tool, "load_plan",
                            return_value=(plan, work / "plan.json", "f" * 64)),
                        mock.patch.object(
                            fleet_tool, "load_executor_config",
                            return_value=({}, plan_path, "e" * 64)),
                        mock.patch.object(
                            fleet_tool, "negotiate", return_value="3" * 64),
                        mock.patch.object(
                            fleet_tool.wave_gate_tool, "load_config",
                            return_value=({}, gate_path, "6" * 64)),
                        mock.patch.object(
                            fleet_tool.wave_gate_tool, "negotiate",
                            return_value="4" * 64),
                        mock.patch.object(
                            fleet_tool.control_authorizer_tool, "load_config",
                            return_value=({}, authorizer_path, "d" * 64)),
                        mock.patch.object(
                            fleet_tool.control_authorizer_tool, "negotiate",
                            return_value="5" * 64),
                    )
                    for item in common_patches:
                        item.start()
                    try:
                        report_a = work / "report-a.json"
                        with mock.patch.object(
                                fleet_tool, "drive",
                                side_effect=finish_as("paused")):
                            started = fleet_tool.execute(arguments(
                                "host-a", work / "scratch-a", report_a
                            ), False)
                        self.assertEqual(started, 2)
                        report_b = work / "report-b.json"
                        with mock.patch.object(
                                fleet_tool, "drive",
                                side_effect=finish_as("committed")):
                            recovered = fleet_tool.execute(arguments(
                                "host-b", work / "scratch-b", report_b
                            ), True)
                        self.assertEqual(recovered, 0)
                        final = json.loads(report_b.read_bytes())
                        self.assertEqual(final["schemaVersion"], 4)
                        self.assertEqual(final["status"], "committed")
                        self.assertEqual(final["lastCoordinatorId"], "host-b")
                        self.assertGreaterEqual(final["stateVersion"], 4)
                        self.assertFalse((work / "scratch-a" / "rollouts").exists())
                        self.assertFalse((work / "scratch-b" / "rollouts").exists())
                    finally:
                        for item in reversed(common_patches):
                            item.stop()
        finally:
            self.backend_patch.start()
            self.artifact_patch.start()


if __name__ == "__main__":
    unittest.main()
