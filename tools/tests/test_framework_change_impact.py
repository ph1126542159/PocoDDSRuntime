import argparse
import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "framework_change_impact", ROOT / "tools/framework_change_impact.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FrameworkChangeImpactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = MODULE.load_catalog(ROOT / "contracts/framework-components.json")

    def evidence(self, report, *, full_suite, labels=None, owners=None):
        return {
            "schemaVersion": 1,
            "operation": "framework-ci-execution-evidence",
            "reportSha256": MODULE.document_digest(report),
            "selection": "full-suite" if full_suite else "affected-labels",
            "fullSuitePassed": full_suite,
            "passedLabels": sorted(report["testLabels"] if labels is None else labels),
            "executedTestCount": 1,
            "executedTests": ["fixture-test"],
            "ctestConfig": "Release",
            "ctestCatalogSha256": "0" * 64,
            "approvedOwners": sorted(report["owners"] if owners is None else owners),
        }

    def test_local_change_propagates_to_dependents_and_owners(self):
        report = MODULE.analyze(
            self.catalog,
            ["platform/BundleManagement/src/BundleManager.cpp"],
        )
        self.assertFalse(report["fullSuite"])
        reasons = {item["id"]: item["reason"] for item in report["components"]}
        self.assertEqual(reasons["bundle-management"], "changed")
        self.assertEqual(reasons["launcher"], "dependency")
        self.assertEqual(reasons["server"], "dependency")
        self.assertEqual(reasons["webui"], "dependency")
        self.assertIn("team/osp-runtime", report["owners"])
        self.assertIn("bundle-deployment", report["testLabels"])

    def test_production_services_have_separate_team_ownership_boundaries(self):
        cases = (
            (
                "services/SchedulerRuntime/src/SchedulerRuntimeBundle.cpp",
                "governance-services", "team/runtime-governance", "scheduling",
            ),
            (
                "services/DeviceGateway/src/BundleActivator.cpp",
                "gateway-services", "team/device-platform", "gateway",
            ),
            (
                "services/UnitsOfMeasure/src/UnitsOfMeasureService.cpp",
                "utility-services", "team/services", "service",
            ),
        )
        for path, component_id, owner, label in cases:
            with self.subTest(path=path):
                report = MODULE.analyze(self.catalog, [path])
                self.assertFalse(report["fullSuite"])
                changed = [
                    item for item in report["components"] if item["reason"] == "changed"
                ]
                self.assertEqual(len(changed), 1)
                self.assertEqual(changed[0]["id"], component_id)
                self.assertEqual(changed[0]["owner"], owner)
                self.assertIn(label, changed[0]["testLabels"])
                expected_target = {
                    "governance-services": "PDRGovernanceServices",
                    "gateway-services": "PDRGatewayServices",
                    "utility-services": "PDRUtilityServices",
                }[component_id]
                self.assertEqual(changed[0]["buildTargets"], [expected_target])
                self.assertIn(expected_target, report["buildTargets"])

    def test_docs_only_is_narrow_but_governance_and_unknown_fail_closed(self):
        docs = MODULE.analyze(self.catalog, ["docs/security/README.md"])
        self.assertTrue(docs["docsOnly"])
        self.assertEqual(docs["testLabels"], ["docs"])

        governance = MODULE.analyze(self.catalog, ["contracts/framework-components.json"])
        self.assertTrue(governance["fullSuite"])
        self.assertIn("global:contracts/framework-components.json",
                      governance["fullSuiteReasons"])

        unknown = MODULE.analyze(self.catalog, ["new-top-level/file.cpp"])
        self.assertTrue(unknown["fullSuite"])
        self.assertIn("unclassified:new-top-level/file.cpp",
                      unknown["fullSuiteReasons"])

    def test_gate_requires_all_labels_or_full_suite_and_optional_owners(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path, evidence_path = root / "impact.json", root / "evidence.json"
            report = MODULE.analyze(
                self.catalog, ["platform/BundleManagement/src/BundleManager.cpp"]
            )
            report_path.write_text(json.dumps(report), encoding="utf-8")
            evidence_path.write_text(json.dumps(self.evidence(
                report, full_suite=False, labels=report["testLabels"][:-1]
            )), encoding="utf-8")
            args = argparse.Namespace(
                report=report_path, evidence=evidence_path, require_owner_approvals=True
            )
            self.assertNotEqual(MODULE.gate_command(args), 0)

            evidence_path.write_text(json.dumps(self.evidence(
                report, full_suite=False
            )), encoding="utf-8")
            self.assertEqual(MODULE.gate_command(args), 0)

            full = MODULE.analyze(self.catalog, ["CMakeLists.txt"])
            report_path.write_text(json.dumps(full), encoding="utf-8")
            evidence_path.write_text(json.dumps(self.evidence(
                full, full_suite=False
            )), encoding="utf-8")
            self.assertNotEqual(MODULE.gate_command(args), 0)
            evidence_path.write_text(json.dumps(self.evidence(
                full, full_suite=True
            )), encoding="utf-8")
            self.assertEqual(MODULE.gate_command(args), 0)

    def test_gate_rejects_evidence_bound_to_different_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path, evidence_path = root / "impact.json", root / "evidence.json"
            report = MODULE.analyze(self.catalog, ["docs/README.md"])
            evidence = self.evidence(report, full_suite=False)
            report["changedPaths"] = ["docs/security/README.md"]
            report_path.write_text(json.dumps(report), encoding="utf-8")
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            args = argparse.Namespace(
                report=report_path, evidence=evidence_path,
                require_owner_approvals=False,
            )
            self.assertNotEqual(MODULE.gate_command(args), 0)

    def test_execute_runs_affected_ctest_selection_and_writes_bound_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path, evidence_path = root / "impact.json", root / "evidence.json"
            report = MODULE.analyze(self.catalog, ["docs/README.md"])
            report_path.write_text(json.dumps(report), encoding="utf-8")
            query = MODULE.subprocess.CompletedProcess(
                [], 0, stdout=json.dumps({
                    "tests": [
                        {
                            "name": "documentation-files",
                            "properties": [{"name": "LABELS", "value": ["docs"]}],
                        },
                        {
                            "name": "docs-links",
                            "properties": [{"name": "LABELS", "value": ["docs"]}],
                        },
                    ]
                }), stderr="",
            )
            run = MODULE.subprocess.CompletedProcess([], 0)
            args = argparse.Namespace(
                report=report_path,
                ctest=Path("ctest"),
                test_dir=root,
                config="Release",
                evidence=evidence_path,
                force_full_suite=False,
            )
            with mock.patch.object(MODULE.subprocess, "run", side_effect=[query, run]) as invoke:
                self.assertEqual(MODULE.execute_command(args), 0)
            self.assertIn("-L", invoke.call_args_list[0].args[0])
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["selection"], "affected-labels")
            self.assertEqual(evidence["executedTestCount"], 2)
            self.assertEqual(evidence["reportSha256"], MODULE.document_digest(report))
            gate_args = argparse.Namespace(
                report=report_path, evidence=evidence_path,
                require_owner_approvals=False,
            )
            self.assertEqual(MODULE.gate_command(gate_args), 0)

    def test_execute_rejects_narrow_profile_as_full_suite_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path, evidence_path = root / "impact.json", root / "evidence.json"
            report = MODULE.analyze(self.catalog, ["CMakeLists.txt"])
            report_path.write_text(json.dumps(report), encoding="utf-8")
            query = MODULE.subprocess.CompletedProcess(
                [], 0, stdout=json.dumps({
                    "tests": [{
                        "name": "documentation-files",
                        "properties": [{"name": "LABELS", "value": ["docs"]}],
                    }]
                }), stderr="",
            )
            args = argparse.Namespace(
                report=report_path,
                ctest=Path("ctest"),
                test_dir=root,
                config="Release",
                evidence=evidence_path,
                force_full_suite=True,
            )
            with mock.patch.object(MODULE.subprocess, "run", return_value=query) as invoke:
                self.assertNotEqual(MODULE.execute_command(args), 0)
            self.assertEqual(invoke.call_count, 1)
            self.assertFalse(evidence_path.exists())

    def test_catalog_rejects_dependency_cycles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            document = json.loads(json.dumps(self.catalog))
            runtime = next(item for item in document["components"]
                           if item["id"] == "runtime-core")
            runtime["requires"] = ["server"]
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cycle"):
                MODULE.load_catalog(path)

    def test_catalog_rejects_duplicate_build_target_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            document = json.loads(json.dumps(self.catalog))
            document["components"][0]["buildTargets"] = ["SharedTarget"]
            document["components"][1]["buildTargets"] = ["SharedTarget"]
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "owned by both"):
                MODULE.load_catalog(path)


if __name__ == "__main__":
    unittest.main()
