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


if __name__ == "__main__":
    unittest.main()
