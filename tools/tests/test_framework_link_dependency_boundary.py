import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "framework_link_dependency_boundary",
    ROOT / "tools/framework_link_dependency_boundary.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def catalog(service_requires: list[str]) -> dict:
    return {
        "schemaVersion": 1,
        "product": "PocoDDSRuntimeFrameworkComponents",
        "globalPaths": ["CMakeLists.txt", "tests/", "tools/"],
        "components": [
            {"id": "core", "owner": "team/core", "paths": ["core/"],
             "requires": [], "buildTargets": ["Core"], "testLabels": ["core"]},
            {"id": "adapter", "owner": "team/adapter", "paths": ["adapter/"],
             "requires": ["core"], "buildTargets": ["Adapter"],
             "testLabels": ["adapter"]},
            {"id": "service", "owner": "team/service", "paths": ["service/"],
             "requires": service_requires, "buildTargets": ["Service"],
             "testLabels": ["service"]},
        ],
    }


def target(root: Path, name: str, component: str, dependencies=None,
           sources=None, unresolved=None, target_type="STATIC_LIBRARY",
           include_directories=None, unresolved_includes=None) -> dict:
    return {
        "name": name,
        "type": target_type,
        "sourceDirectory": str(root / component),
        "sources": sources if sources is not None else [f"src/{name}.cpp"],
        "dependencies": dependencies or [],
        "unresolvedLinkItems": unresolved or [],
        "includeDirectories": include_directories or [],
        "unresolvedIncludeItems": unresolved_includes or [],
    }


def manifest(root: Path, targets: list[dict]) -> dict:
    return {
        "schemaVersion": 1,
        "operation": "cmake-target-link-manifest",
        "profile": "unit-test",
        "sourceRoot": str(root),
        "buildRoot": str(root / "build"),
        "targets": targets,
    }


class FrameworkLinkDependencyBoundaryTests(unittest.TestCase):
    def fixture(self, root: Path) -> None:
        for component in ("core", "adapter", "service"):
            (root / component / "src").mkdir(parents=True)
            (root / component / "src" / f"{component.title()}.cpp").write_text(
                "// fixture\n", encoding="utf-8"
            )

    def test_declared_direct_target_link_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            document = manifest(root, [
                target(root, "Core", "core"),
                target(root, "Service", "service", ["Core"]),
            ])
            report = MODULE.analyze(root, catalog(["core"]), document)
            self.assertTrue(report["passed"])
            self.assertEqual(report["analyzedProductionTargets"], 2)
            self.assertEqual(report["observedEdges"][0]["consumer"], "service")

    def test_direct_link_cannot_borrow_a_transitive_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            document = manifest(root, [
                target(root, "Core", "core"),
                target(root, "Adapter", "adapter", ["Core"]),
                target(root, "Service", "service", ["Adapter", "Core"]),
            ])
            report = MODULE.analyze(root, catalog(["adapter"]), document)
            self.assertFalse(report["passed"])
            violation = report["violations"][0]
            self.assertEqual((violation["consumer"], violation["provider"]),
                             ("service", "core"))
            self.assertEqual(violation["evidence"][0]["consumerTarget"], "Service")

    def test_test_target_is_excluded_from_production_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            document = manifest(root, [
                target(root, "Core", "core"),
                target(root, "ServiceTests", "service", ["Core"],
                       sources=["tests/ServiceTests.cpp"], target_type="EXECUTABLE"),
            ])
            report = MODULE.analyze(root, catalog([]), document)
            self.assertTrue(report["passed"])
            self.assertEqual(report["analyzedProductionTargets"], 1)

    def test_mixed_component_target_ownership_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            mixed = target(root, "Mixed", ".", sources=[
                "core/src/Core.cpp", "service/src/Service.cpp"
            ])
            report = MODULE.analyze(root, catalog([]), manifest(root, [mixed]))
            self.assertFalse(report["passed"])
            self.assertEqual(report["ambiguousTargets"][0]["owners"],
                             ["core", "service"])

    def test_unclassified_target_and_unresolved_link_item_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            (root / "mystery/src").mkdir(parents=True)
            document = manifest(root, [
                target(root, "Mystery", "mystery"),
                target(root, "Service", "service",
                       unresolved=["$<$<BOOL:1>:Core>"]),
            ])
            report = MODULE.analyze(root, catalog([]), document)
            self.assertFalse(report["passed"])
            self.assertEqual(report["unclassifiedTargets"][0]["target"], "Mystery")
            self.assertEqual(report["unresolvedLinkItems"][0]["target"], "Service")

    def test_declared_dependency_cannot_expose_provider_private_include_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            document = manifest(root, [
                target(root, "Core", "core"),
                target(root, "Service", "service", ["Core"],
                       include_directories=[str(root / "core/src")]),
            ])
            report = MODULE.analyze(root, catalog(["core"]), document)
            self.assertFalse(report["passed"])
            violation = report["privateIncludeDirectoryViolations"][0]
            self.assertEqual((violation["consumer"], violation["provider"]),
                             ("service", "core"))
            self.assertEqual(violation["includeDirectory"], "core/src")

    def test_provider_public_include_directory_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            (root / "core/include/Core").mkdir(parents=True)
            document = manifest(root, [
                target(root, "Core", "core"),
                target(root, "Service", "service", ["Core"],
                       include_directories=[str(root / "core/include")]),
            ])
            report = MODULE.analyze(root, catalog(["core"]), document)
            self.assertTrue(report["passed"])

    def test_unresolved_include_directory_expression_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            document = manifest(root, [target(
                root, "Service", "service",
                unresolved_includes=["$<$<BOOL:1>:E:/private>"]
            )])
            report = MODULE.analyze(root, catalog([]), document)
            self.assertFalse(report["passed"])
            self.assertEqual(report["unresolvedIncludeItems"][0]["target"], "Service")

    def test_explicit_build_target_owns_an_aggregate_outside_component_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            document = catalog([])
            document["components"].append({
                "id": "plugin-sdk", "owner": "team/plugin-sdk",
                "paths": ["cmake/PluginSDK.cmake"], "requires": [],
                "buildTargets": ["Plugins"], "testLabels": ["sdk"],
            })
            aggregate = target(root, "Plugins", "unowned", sources=[],
                               target_type="INTERFACE_LIBRARY")
            report = MODULE.analyze(root, document, manifest(root, [aggregate]))
            self.assertTrue(report["passed"])
            self.assertEqual(report["analyzedProductionTargets"], 1)

    def test_cli_writes_failure_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            catalog_path = root / "catalog.json"
            manifest_path = root / "manifest.json"
            report_path = root / "report.json"
            catalog_path.write_text(json.dumps(catalog([])), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest(root, [
                target(root, "Core", "core"),
                target(root, "Service", "service", ["Core"]),
            ])), encoding="utf-8")
            result = MODULE.validate_command(argparse.Namespace(
                root=root, catalog=catalog_path, manifest=manifest_path,
                report=report_path, expect_profile="unit-test"
            ))
            self.assertEqual(result, 1)
            self.assertFalse(json.loads(
                report_path.read_text(encoding="utf-8"))["passed"])

    def test_cli_rejects_a_stale_profile_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            catalog_path = root / "catalog.json"
            manifest_path = root / "manifest.json"
            catalog_path.write_text(json.dumps(catalog([])), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest(root, [
                target(root, "Core", "core"),
            ])), encoding="utf-8")
            result = MODULE.validate_command(argparse.Namespace(
                root=root, catalog=catalog_path, manifest=manifest_path,
                report=None, expect_profile="server"
            ))
            self.assertEqual(result, 1)

    def test_matrix_requires_exact_profiles_and_all_reports_to_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            report_paths = []
            for profile in ("desktop-lite", "server"):
                document = manifest(root, [target(root, "Core", "core")])
                document["profile"] = profile
                report = MODULE.analyze(root, catalog([]), document)
                path = root / f"{profile}.json"
                path.write_text(json.dumps(report), encoding="utf-8")
                report_paths.append(path)
            output = root / "matrix.json"
            args = argparse.Namespace(
                required_profile=["desktop-lite", "server"],
                profile_report=report_paths, output=output,
            )
            self.assertEqual(MODULE.matrix_command(args), 0)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["passed"])

            args.required_profile.append("robotics")
            self.assertEqual(MODULE.matrix_command(args), 1)
            failed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(failed["missingProfiles"], ["robotics"])

    def test_matrix_rejects_duplicate_unexpected_and_inconsistent_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            paths = []
            for profile in ("server", "robotics"):
                document = manifest(root, [target(root, "Core", "core")])
                document["profile"] = profile
                report = MODULE.analyze(root, catalog([]), document)
                path = root / f"{profile}.json"
                path.write_text(json.dumps(report), encoding="utf-8")
                paths.append(path)
            output = root / "matrix.json"
            args = argparse.Namespace(
                required_profile=["server"],
                profile_report=[paths[0], paths[0], paths[1]], output=output,
            )
            self.assertEqual(MODULE.matrix_command(args), 1)
            failed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(failed["duplicateProfiles"], ["server"])
            self.assertEqual(failed["unexpectedProfiles"], ["robotics"])

            inconsistent = json.loads(paths[0].read_text(encoding="utf-8"))
            inconsistent["passed"] = False
            paths[0].write_text(json.dumps(inconsistent), encoding="utf-8")
            args.profile_report = [paths[0]]
            self.assertEqual(MODULE.matrix_command(args), 1)


if __name__ == "__main__":
    unittest.main()
