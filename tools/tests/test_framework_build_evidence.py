import argparse
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
    "framework_build_evidence", ROOT / "tools/framework_build_evidence.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

IMPACT_SPEC = importlib.util.spec_from_file_location(
    "framework_change_impact_fixture", ROOT / "tools/framework_change_impact.py"
)
IMPACT = importlib.util.module_from_spec(IMPACT_SPEC)
assert IMPACT_SPEC.loader is not None
IMPACT_SPEC.loader.exec_module(IMPACT)


class FrameworkBuildEvidenceTests(unittest.TestCase):
    def fixture(self, root: Path, changed_path="services/A/src/Member.cpp"):
        source = root / changed_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("int member = 1;\n", encoding="utf-8")
        build = root / "build"
        reports = build / "reports"
        reports.mkdir(parents=True)
        (build / "CMakeCache.txt").write_text(
            "CMAKE_GENERATOR:INTERNAL=Ninja\nPDR_PROFILE:STRING=server\n",
            encoding="utf-8",
        )
        links = reports / "links.json"
        groups = reports / "groups.json"
        dependencies = root / "release/dependencies.json"
        dependencies.parent.mkdir(parents=True)
        dependencies.write_text('{"schemaVersion":1,"packages":[]}\n', encoding="utf-8")
        links.write_text(json.dumps({
            "schemaVersion": 1, "operation": "cmake-target-link-manifest",
            "profile": "server", "sourceRoot": str(root),
            "buildRoot": str(build), "targets": [],
        }), encoding="utf-8")
        groups.write_text(json.dumps({
            "schemaVersion": 1, "operation": "framework-component-build-groups",
            "profile": "server", "groups": [{
                "component": "service", "target": "ServiceGroup", "members": ["Service"],
            }],
        }), encoding="utf-8")
        catalog = {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeFrameworkComponents",
            "globalPaths": ["CMakeLists.txt"],
            "components": [
                {
                    "id": "docs", "owner": "team/docs", "paths": ["docs/"],
                    "requires": [], "buildTargets": [], "testLabels": ["docs"],
                },
                {
                    "id": "service", "owner": "team/service", "paths": ["services/A/"],
                    "requires": [], "buildTargets": ["ServiceGroup"],
                    "testLabels": ["service"],
                },
                {
                    "id": "server", "owner": "team/runtime", "paths": ["server/"],
                    "requires": ["service"], "buildTargets": ["pdr-runtime"],
                    "testLabels": ["runtime"],
                },
            ],
        }
        report = IMPACT.analyze(catalog, [changed_path])
        report_path = reports / "impact.json"
        evidence = reports / "build-evidence.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        args = argparse.Namespace(
            root=root, report=report_path, build_dir=build, links=links,
            groups=groups, dependencies=dependencies,
            source_revision="abcdef1234567", evidence=evidence,
            cmake=Path("cmake"), configuration="Release", parallelism=2,
            force_full_build=False,
        )
        return args, source

    @staticmethod
    def version_result():
        return MODULE.subprocess.CompletedProcess(
            [], 0, stdout="cmake version 4.0.0\n", stderr=""
        )

    def gate(self, args):
        with mock.patch.object(
            MODULE, "cmake_version", return_value="cmake version 4.0.0"
        ):
            return MODULE.gate_command(args)

    def test_affected_build_writes_bound_evidence_and_gate_accepts_it(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _ = self.fixture(Path(directory))
            build_result = MODULE.subprocess.CompletedProcess([], 0)
            with mock.patch.object(
                MODULE.subprocess, "run", side_effect=[self.version_result(), build_result]
            ) as invoke:
                self.assertEqual(MODULE.execute_command(args), 0)
            build_command = invoke.call_args_list[1].args[0]
            self.assertIn("--target", build_command)
            self.assertIn("ServiceGroup", build_command)
            self.assertIn("pdr-runtime", build_command)
            evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
            self.assertEqual(evidence["selection"], "affected-targets")
            self.assertEqual(evidence["requestedTargets"], ["ServiceGroup", "pdr-runtime"])
            self.assertEqual(evidence["executedTargets"], evidence["requestedTargets"])
            self.assertEqual(self.gate(args), 0)

    def test_gate_rejects_source_and_build_input_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            args, source = self.fixture(Path(directory))
            with mock.patch.object(MODULE.subprocess, "run", side_effect=[
                self.version_result(), MODULE.subprocess.CompletedProcess([], 0)
            ]):
                self.assertEqual(MODULE.execute_command(args), 0)
            source.write_text("int member = 2;\n", encoding="utf-8")
            self.assertNotEqual(self.gate(args), 0)
            source.write_text("int member = 1;\n", encoding="utf-8")
            args.dependencies.write_text(
                '{"schemaVersion":1,"packages":[{"name":"new"}]}\n', encoding="utf-8"
            )
            self.assertNotEqual(self.gate(args), 0)

    def test_gate_rejects_evidence_tampering_and_other_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _ = self.fixture(Path(directory))
            with mock.patch.object(MODULE.subprocess, "run", side_effect=[
                self.version_result(), MODULE.subprocess.CompletedProcess([], 0)
            ]):
                self.assertEqual(MODULE.execute_command(args), 0)
            evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
            evidence["parallelism"] = 7
            args.evidence.write_text(json.dumps(evidence), encoding="utf-8")
            self.assertNotEqual(self.gate(args), 0)
            evidence["parallelism"] = 2
            args.evidence.write_text(json.dumps(evidence), encoding="utf-8")
            args.source_revision = "fedcba7654321"
            self.assertNotEqual(self.gate(args), 0)

    def test_failed_build_does_not_write_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _ = self.fixture(Path(directory))
            with mock.patch.object(MODULE.subprocess, "run", side_effect=[
                self.version_result(), MODULE.subprocess.CompletedProcess([], 2)
            ]):
                self.assertNotEqual(MODULE.execute_command(args), 0)
            self.assertFalse(args.evidence.exists())

    def test_forced_full_build_uses_default_target_and_gate_accepts_it(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _ = self.fixture(Path(directory))
            args.force_full_build = True
            with mock.patch.object(MODULE.subprocess, "run", side_effect=[
                self.version_result(), MODULE.subprocess.CompletedProcess([], 0)
            ]) as invoke:
                self.assertEqual(MODULE.execute_command(args), 0)
            build_command = invoke.call_args_list[1].args[0]
            self.assertNotIn("--target", build_command)
            evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
            self.assertEqual(evidence["selection"], "full-build")
            self.assertEqual(evidence["executedTargets"], ["<default>"])
            self.assertEqual(self.gate(args), 0)

    def test_docs_only_records_no_build_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, _ = self.fixture(root, "docs/README.md")
            with mock.patch.object(
                MODULE.subprocess, "run", return_value=self.version_result()
            ) as invoke:
                self.assertEqual(MODULE.execute_command(args), 0)
            self.assertEqual(invoke.call_count, 1)
            evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
            self.assertEqual(evidence["selection"], "docs-only")
            self.assertEqual(evidence["command"], [])
            self.assertEqual(evidence["executedTargets"], [])
            self.assertEqual(self.gate(args), 0)


if __name__ == "__main__":
    unittest.main()
