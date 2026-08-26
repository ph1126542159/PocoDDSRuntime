import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "pdr.py"


class ProjectManagerTests(unittest.TestCase):
    def run_tool(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *arguments], check=False,
            capture_output=True, text=True,
        )

    def test_create_validate_and_resolve_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = self.run_tool(
                "project", "create", "WarehouseRobot", "--output", str(root),
                "--profile", "robotics", "--runtime-version", "0.1.x",
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            project = root / "WarehouseRobot"
            manifest = project / "pdr-project.yaml"
            self.assertTrue(manifest.is_file())
            self.assertTrue((project / "adapters/hardware").is_dir())
            cmake = (project / "CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn("PDR_PROJECT_BUILD_MANAGEMENT", cmake)
            self.assertIn("pdr-project.components.cmake", cmake)
            composition = (project / "pdr-project.components.cmake").read_text(
                encoding="utf-8"
            )
            self.assertIn("PDR_PROJECT_MANIFEST_SHA256", composition)
            self.assertNotIn("file(GLOB", cmake + composition)
            validated = self.run_tool(
                "project", "validate", str(manifest),
                "--report", str(project / "validation.json"),
            )
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
            lock = project / "pdr-project.lock.json"
            resolved = self.run_tool(
                "project", "resolve", str(manifest), "--output", str(lock),
            )
            self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)
            evidence = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(evidence["project"]["name"], "warehouse-robot")
            self.assertEqual(evidence["project"]["version"], "0.1.0")
            self.assertEqual(evidence["project"]["runtime"]["profile"], "robotics")
            self.assertGreater(evidence["sourceFileCount"], 0)
            resolved_again = self.run_tool(
                "project", "resolve", str(manifest), "--output", str(lock),
            )
            self.assertEqual(resolved_again.returncode, 0, resolved_again.stdout + resolved_again.stderr)
            repeated = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(repeated["sourceTreeSha256"], evidence["sourceTreeSha256"])
            self.assertEqual(repeated["sourceFileCount"], evidence["sourceFileCount"])

            versioned = self.run_tool(
                "project", "version", str(manifest), "1.4.0-rc.1"
            )
            self.assertEqual(versioned.returncode, 0, versioned.stdout + versioned.stderr)
            updated = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(updated["version"], "1.4.0-rc.1")
            composition = (project / "pdr-project.components.cmake").read_text(
                encoding="utf-8"
            )
            import hashlib
            self.assertIn(hashlib.sha256(manifest.read_bytes()).hexdigest(), composition)

    def test_validation_rejects_escape_duplicate_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = self.run_tool("project", "create", "SafeRobot", "--output", str(root))
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            manifest = root / "SafeRobot/pdr-project.yaml"
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["components"]["modules"] = ["../escape", "../escape"]
            document["unexpected"] = True
            manifest.write_text(json.dumps(document), encoding="utf-8")
            report = root / "invalid.json"
            validated = self.run_tool(
                "project", "validate", str(manifest), "--report", str(report),
            )
            self.assertEqual(validated.returncode, 1)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(evidence["passed"])
            self.assertIn("unknown project manifest fields", evidence["error"])

    def test_create_refuses_nonempty_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "ExistingRobot"
            destination.mkdir()
            (destination / "owned.txt").write_text("keep", encoding="utf-8")
            created = self.run_tool(
                "project", "create", "ExistingRobot", "--output", directory,
            )
            self.assertNotEqual(created.returncode, 0)
            self.assertEqual((destination / "owned.txt").read_text(encoding="utf-8"), "keep")

    def test_desktop_lite_records_minimal_model_and_rejects_management_components(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = self.run_tool(
                "project", "create", "DesktopTool", "--output", str(root),
                "--profile", "desktop-lite",
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            manifest = root / "DesktopTool/pdr-project.yaml"
            document = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(document["runtime"]["host"], "static")
            self.assertEqual(document["runtime"]["transports"], ["inproc"])
            cmake = (manifest.parent / "CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn("PDR_PROJECT_BUILD_APPLICATION", cmake)

            device = manifest.parent / "devices/HeavyDevice"
            device.mkdir(parents=True)
            (device / "CMakeLists.txt").write_text(
                "add_library(HeavyDevice INTERFACE)\n", encoding="utf-8"
            )
            document["components"]["devices"] = ["devices/HeavyDevice"]
            manifest.write_text(json.dumps(document), encoding="utf-8")
            rejected = self.run_tool("project", "validate", str(manifest))
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("desktop-lite supports modules and services only",
                          rejected.stdout + rejected.stderr)

    def test_validation_rejects_incomplete_component_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = self.run_tool("project", "create", "StructuredRobot", "--output", str(root))
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            project = root / "StructuredRobot"
            manifest = project / "pdr-project.yaml"
            document = json.loads(manifest.read_text(encoding="utf-8"))
            incomplete = project / "modules/IncompleteModule"
            incomplete.mkdir()
            document["components"]["modules"] = ["modules/IncompleteModule"]
            manifest.write_text(json.dumps(document), encoding="utf-8")

            rejected = self.run_tool("project", "validate", str(manifest))
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("must contain CMakeLists.txt", rejected.stdout + rejected.stderr)

            (incomplete / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.24)\n", encoding="utf-8"
            )
            accepted = self.run_tool("project", "validate", str(manifest))
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)

    def test_new_component_auto_registers_and_remove_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = self.run_tool(
                "project", "create", "ComposableRobot", "--output", str(root),
                "--profile", "robotics",
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            project = root / "ComposableRobot"
            generated = self.run_tool(
                "new", "robot-module", "ChargingModule",
                "--output", str(project / "modules"),
            )
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            self.assertIn("registered robot-module", generated.stdout)
            manifest = project / "pdr-project.yaml"
            document = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(document["components"]["robotModules"],
                             ["modules/ChargingModule"])
            composition = (project / "pdr-project.components.cmake").read_text(
                encoding="utf-8"
            )
            self.assertIn("modules/ChargingModule", composition)

            listed = self.run_tool("project", "list", str(manifest), "--json")
            self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
            records = json.loads(listed.stdout)
            self.assertEqual(records, [{"kind": "robot-module", "path": "modules/ChargingModule"}])

            removed = self.run_tool(
                "project", "remove", str(manifest), "robot-module", "modules/ChargingModule"
            )
            self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
            self.assertTrue((project / "modules/ChargingModule/CMakeLists.txt").is_file())
            document = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(document["components"]["robotModules"], [])

    def test_dependency_registry_is_sorted_and_duplicate_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = self.run_tool("project", "create", "DependencyRobot", "--output", str(root))
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            manifest = root / "DependencyRobot/pdr-project.yaml"
            for name, version in (("ZetaSDK", "2.0"), ("AlphaSDK", "1.0")):
                added = self.run_tool(
                    "project", "dependency", "add", str(manifest), name,
                    "--version", version, "--license", "MIT",
                    "--download", f"https://example.invalid/{name}.zip",
                )
                self.assertEqual(added.returncode, 0, added.stdout + added.stderr)
            listed = self.run_tool(
                "project", "dependency", "list", str(manifest), "--json"
            )
            self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
            dependencies = json.loads(listed.stdout)
            self.assertEqual([item["name"] for item in dependencies], ["AlphaSDK", "ZetaSDK"])
            duplicate = self.run_tool(
                "project", "dependency", "add", str(manifest), "AlphaSDK",
                "--version", "9.0", "--license", "MIT",
                "--download", "https://example.invalid/duplicate.zip",
            )
            self.assertNotEqual(duplicate.returncode, 0)
            removed = self.run_tool(
                "project", "dependency", "remove", str(manifest), "AlphaSDK"
            )
            self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)

    def test_change_impact_selects_direct_and_transitive_component_owners(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = self.run_tool(
                "project", "create", "ImpactProduct", "--output", str(root),
                "--profile", "edge-industrial",
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            project = root / "ImpactProduct"
            for kind, name, folder in (
                ("module", "SharedModel", "modules"),
                ("service", "AlarmService", "services"),
            ):
                generated = self.run_tool(
                    "new", kind, name, "--output", str(project / folder)
                )
                self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            dependency = self.run_tool(
                "component", "dependency", "add",
                str(project / "services/AlarmService"), "shared-model",
            )
            self.assertEqual(dependency.returncode, 0, dependency.stdout + dependency.stderr)
            manifest = project / "pdr-project.yaml"
            synced = self.run_tool("project", "sync", str(manifest))
            self.assertEqual(synced.returncode, 0, synced.stdout + synced.stderr)

            report_path = project / "build/impact.json"
            impacted = self.run_tool(
                "project", "impact", str(manifest),
                "modules/SharedModel/src/SharedModel.cpp",
                "--output", str(report_path),
            )
            self.assertEqual(impacted.returncode, 0, impacted.stdout + impacted.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(report["frameworkWide"])
            self.assertEqual(
                [(item["id"], item["reason"]) for item in report["components"]],
                [("alarm-service", "dependency"), ("shared-model", "changed")],
            )
            self.assertEqual(report["owners"], ["project"])

            global_change = self.run_tool(
                "project", "impact", str(manifest), "CMakeLists.txt"
            )
            self.assertEqual(
                global_change.returncode, 0, global_change.stdout + global_change.stderr
            )
            self.assertTrue(json.loads(global_change.stdout)["frameworkWide"])

    def test_component_contracts_order_dependencies_and_reject_cycles_and_reverse_edges(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = self.run_tool(
                "project", "create", "CollaborativeRuntime", "--output", str(root),
                "--profile", "server",
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            project = root / "CollaborativeRuntime"
            for kind, name, folder in (
                ("module", "SharedModel", "modules"),
                ("service", "InventoryService", "services"),
                ("bundle", "InventoryBundle", "bundles"),
                ("subprocess", "VisionWorker", "subprocesses"),
            ):
                generated = self.run_tool(
                    "new", kind, name, "--output", str(project / folder)
                )
                self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)

            def contract(relative: str) -> tuple[Path, dict]:
                path = project / relative / "pdr-component.json"
                return path, json.loads(path.read_text(encoding="utf-8"))

            for relative, requires in (
                ("services/InventoryService", ["shared-model"]),
                ("bundles/InventoryBundle", ["inventory-service"]),
                ("subprocesses/VisionWorker", ["shared-model"]),
            ):
                path, document = contract(relative)
                document["requires"] = requires
                path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

            manifest = project / "pdr-project.yaml"
            synced = self.run_tool("project", "sync", str(manifest))
            self.assertEqual(synced.returncode, 0, synced.stdout + synced.stderr)
            composition = (project / "pdr-project.components.cmake").read_text(
                encoding="utf-8"
            )
            self.assertLess(composition.index("modules/SharedModel"),
                            composition.index("services/InventoryService"))
            self.assertLess(composition.index("services/InventoryService"),
                            composition.index("bundles/InventoryBundle"))
            self.assertIn("pdr_generated_module_shared_model", composition)
            self.assertIn("PDR_COMPONENT_OWNER", composition)

            module_path, module = contract("modules/SharedModel")
            module["requires"] = ["inventory-service"]
            module_path.write_text(json.dumps(module, indent=2) + "\n", encoding="utf-8")
            reverse = self.run_tool("project", "validate", str(manifest))
            self.assertNotEqual(reverse.returncode, 0)
            self.assertIn("dependency crosses boundary", reverse.stdout + reverse.stderr)

            module["requires"] = []
            module_path.write_text(json.dumps(module, indent=2) + "\n", encoding="utf-8")
            service_path, service = contract("services/InventoryService")
            service["requires"] = ["shared-model"]
            service_path.write_text(json.dumps(service, indent=2) + "\n", encoding="utf-8")
            second_module = self.run_tool(
                "new", "module", "SharedPolicy", "--output", str(project / "modules")
            )
            self.assertEqual(second_module.returncode, 0,
                             second_module.stdout + second_module.stderr)
            policy_path, policy = contract("modules/SharedPolicy")
            module["requires"] = ["shared-policy"]
            policy["requires"] = ["shared-model"]
            module_path.write_text(json.dumps(module, indent=2) + "\n", encoding="utf-8")
            policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
            cycle = self.run_tool("project", "validate", str(manifest))
            self.assertNotEqual(cycle.returncode, 0)
            self.assertIn("component dependency cycle", cycle.stdout + cycle.stderr)


if __name__ == "__main__":
    unittest.main()
