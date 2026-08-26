import argparse
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "framework_recovery_matrix", ROOT / "tools/framework_recovery_matrix.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FrameworkRecoveryMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = json.loads(
            (ROOT / "contracts/framework-recovery-matrix.json").read_text(encoding="utf-8")
        )
        cls.catalog = MODULE.load_catalog(ROOT / "contracts/framework-components.json")

    def test_repository_matrix_is_strict_and_covers_every_required_scope(self):
        scenarios = MODULE.validate_matrix(self.matrix, self.catalog)
        self.assertEqual(len(scenarios), 30)
        self.assertEqual(
            {item["scope"] for item in scenarios}, set(self.matrix["requiredScopes"])
        )
        desired_state = next(
            item for item in scenarios if item["id"] == "PDR-REC-0013"
        )
        self.assertEqual(desired_state["owner"], "team/osp-runtime")
        self.assertEqual(
            {item["marker"] for item in desired_state["assertions"]},
            {
                "stoppedAcrossRestart=1",
                "runningAcrossRestart=1",
                "previousRecovery=1",
                "corruptionFailClosed=1",
                "transactionalMutation=1",
                "crashLoopDurable=1",
                "rootConfined=1",
                "leaseExclusive=1",
                "statusObservable=1",
                "onlineScrub=1",
                "scrubRepair=1",
                "casRecommit=1",
                "staleGeneration=1",
                "zeroLifecycleEffect=1",
                "managerUnavailable=1",
                "disabledRejected=1",
            },
        )
        durability = next(
            item for item in scenarios if item["id"] == "PDR-REC-0014"
        )
        self.assertEqual(durability["scope"], "persistence")
        self.assertEqual(
            {item["marker"] for item in durability["assertions"]},
            {
                "stagingCrashSafe=1",
                "previousCrashSafe=1",
                "primaryCrashSafe=1",
                "retryCommit=1",
                "metadataDurable=1",
            },
        )
        online_scrub = next(
            item for item in scenarios if item["id"] == "PDR-REC-0015"
        )
        self.assertEqual(online_scrub["test"],
                         "runtime-process-desired-state-integration")
        self.assertEqual(
            {item["marker"] for item in online_scrub["assertions"]},
            {
                "onlineScrub=1",
                "healthDegraded=1",
                "scrubRepair=1",
                "stopped=1",
                "relaunch=0",
                "snapshots=2",
            },
        )
        configuration_preflight = next(
            item for item in scenarios if item["id"] == "PDR-REC-0016"
        )
        self.assertEqual(configuration_preflight["test"],
                         "config-transaction-preflight-smoke")
        self.assertEqual(
            {item["marker"] for item in configuration_preflight["assertions"]},
            {
                "sideEffectFree=1",
                "generationConflict=1",
                "participantOrder=1",
                "commitRepreflight=1",
                "topologyRechecked=1",
                "lifetimeBarrier=1",
            },
        )
        participant_admission = next(
            item for item in scenarios if item["id"] == "PDR-REC-0017"
        )
        self.assertEqual(participant_admission["test"],
                         "configuration-participant-admission-smoke")
        self.assertEqual(
            {item["marker"] for item in participant_admission["assertions"]},
            {
                "rejected=1",
                "readinessDegraded=1",
                "recovery=1",
                "sanitized=1",
                "bounded=1",
            },
        )
        participant_expectation = next(
            item for item in scenarios if item["id"] == "PDR-REC-0018"
        )
        self.assertEqual(participant_expectation["test"],
                         "configuration-participant-expectation-smoke")
        self.assertEqual(
            {item["marker"] for item in participant_expectation["assertions"]},
            {
                "missing=1",
                "satisfied=1",
                "mismatch=1",
                "inactive=1",
                "invalid=1",
                "sanitized=1",
            },
        )
        key_lifecycle = next(
            item for item in scenarios if item["id"] == "PDR-REC-0019"
        )
        self.assertEqual(key_lifecycle["test"],
                         "configuration-key-lifecycle-state-smoke")
        self.assertEqual(
            {item["marker"] for item in key_lifecycle["assertions"]},
            {"published=1", "mismatch=1", "inactive-diagnostic=1", "cycle=1"},
        )

    def test_owner_mismatch_and_missing_scope_fail_closed(self):
        wrong_owner = copy.deepcopy(self.matrix)
        wrong_owner["scenarios"][0]["owner"] = "team/other"
        with self.assertRaisesRegex(ValueError, "owner does not match"):
            MODULE.validate_matrix(wrong_owner, self.catalog)

        missing_scope = copy.deepcopy(self.matrix)
        missing_scope["scenarios"] = [
            item for item in missing_scope["scenarios"]
            if item["scope"] != "persistence"
        ]
        with self.assertRaisesRegex(ValueError, "lacks required scopes"):
            MODULE.validate_matrix(missing_scope, self.catalog)

    def test_duplicate_test_and_unmapped_labels_are_rejected(self):
        duplicate = copy.deepcopy(self.matrix)
        duplicate["scenarios"][1]["test"] = duplicate["scenarios"][0]["test"]
        with self.assertRaisesRegex(ValueError, "assigned more than once"):
            MODULE.validate_matrix(duplicate, self.catalog)

        unmapped = copy.deepcopy(self.matrix)
        unmapped["scenarios"][0]["requiredLabels"] = ["fault-injection"]
        with self.assertRaisesRegex(ValueError, "do not select its component"):
            MODULE.validate_matrix(unmapped, self.catalog)

    def test_ctest_preflight_requires_registration_and_every_label(self):
        scenarios = self.matrix["scenarios"][:2]
        tests = {
            scenarios[0]["test"]: {
                "labels": set(scenarios[0]["requiredLabels"][:-1]),
                "commandSha256": "0" * 64,
                "commandArtifactSetSha256": "1" * 64,
                "runtimeSearchPaths": [],
            },
        }
        records, violations = MODULE.preflight(scenarios, tests)
        self.assertEqual(len(records), 2)
        self.assertEqual(len(violations), 2)
        self.assertTrue(records[0]["missingLabels"])
        self.assertFalse(records[1]["registered"])

    def test_ctest_identity_changes_with_command_and_runtime_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "recovery-test.exe"
            executable.write_bytes(b"first")
            catalog = json.dumps({
                "tests": [{
                    "name": "recovery-test",
                    "command": [str(executable), "--mode", "recovery"],
                    "properties": [{"name": "LABELS", "value": ["recovery"]}],
                }]
            })
            completed = MODULE.subprocess.CompletedProcess([], 0, catalog, "")
            with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
                first, first_digest = MODULE.query_ctest(
                    Path("ctest"), root, "Release", {"recovery-test"}
                )
            executable.write_bytes(b"second")
            with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
                second, second_digest = MODULE.query_ctest(
                    Path("ctest"), root, "Release", {"recovery-test"}
                )
            self.assertNotEqual(first_digest, second_digest)
            self.assertNotEqual(
                first["recovery-test"]["commandArtifactSetSha256"],
                second["recovery-test"]["commandArtifactSetSha256"],
            )

            runtime = root / "bin/runtime.dll"
            runtime.parent.mkdir()
            runtime.write_bytes(b"runtime-one")
            count, runtime_first = MODULE.runtime_artifact_identity(root)
            runtime.write_bytes(b"runtime-two")
            _, runtime_second = MODULE.runtime_artifact_identity(root)
            self.assertEqual(count, 1)
            self.assertNotEqual(runtime_first, runtime_second)

    def test_run_scenario_requires_exit_success_and_all_assertion_markers(self):
        scenario = self.matrix["scenarios"][0]
        output = "FAULT_INJECTION_PASS outage retry duplicate backpressure shutdown\n"
        with mock.patch.object(
            MODULE.subprocess, "run",
            return_value=MODULE.subprocess.CompletedProcess([], 0, output, ""),
        ):
            result = MODULE.run_scenario(
                scenario, Path("ctest"), Path("build"), "Release"
            )
        self.assertTrue(result["passed"])
        self.assertTrue(all(item["observed"] for item in result["assertions"]))

        with mock.patch.object(
            MODULE.subprocess, "run",
            return_value=MODULE.subprocess.CompletedProcess([], 0, "outage retry", ""),
        ), mock.patch.object(MODULE.sys, "stderr"):
            result = MODULE.run_scenario(
                scenario, Path("ctest"), Path("build"), "Release"
            )
        self.assertFalse(result["passed"])

    def test_execute_writes_digest_bound_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix_path = root / "matrix.json"
            catalog_path = root / "catalog.json"
            report_path = root / "evidence.json"
            matrix_path.write_text(json.dumps(self.matrix), encoding="utf-8")
            catalog_path.write_text(json.dumps(self.catalog), encoding="utf-8")
            tests = {
                item["test"]: {
                    "labels": set(item["requiredLabels"]),
                    "commandSha256": "2" * 64,
                    "commandArtifactSetSha256": "3" * 64,
                    "runtimeSearchPaths": [],
                }
                for item in self.matrix["scenarios"]
            }

            def passed_result(item, _ctest, _test_dir, _configuration):
                return {
                    "id": item["id"], "scope": item["scope"],
                    "component": item["component"], "owner": item["owner"],
                    "test": item["test"], "passed": True, "exitCode": 0,
                    "timedOut": False, "elapsedMilliseconds": 1,
                    "outputBytes": 1, "outputSha256": "0" * 64,
                    "assertions": [
                        {**assertion, "observed": True}
                        for assertion in item["assertions"]
                    ],
                    "diagnostic": "",
                }

            args = argparse.Namespace(
                matrix=matrix_path, catalog=catalog_path, ctest=root / "ctest",
                test_dir=root, config="Release", profile="server", report=report_path,
            )
            with (
                mock.patch.object(MODULE, "query_ctest", return_value=(tests, "1" * 64)),
                mock.patch.object(MODULE, "ctest_version", return_value="ctest 4.1"),
                mock.patch.object(MODULE, "run_scenario", side_effect=passed_result),
            ):
                self.assertEqual(MODULE.execute_command(args), 0)
            evidence = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertEqual(evidence["scenarioCount"], 30)
            self.assertEqual(len(evidence["results"]), 30)
            self.assertEqual(evidence["matrixSha256"], MODULE.document_digest(self.matrix))
            MODULE.validate_evidence(evidence)

            evidence["results"][0]["assertions"][0]["observed"] = False
            with self.assertRaisesRegex(ValueError, "pass state is inconsistent"):
                MODULE.validate_evidence(evidence)


if __name__ == "__main__":
    unittest.main()
