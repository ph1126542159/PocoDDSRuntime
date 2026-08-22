import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
TOOL = TOOLS / "pdr.py"
TEMPLATE_TOOL = TOOLS / "project_template.py"


def load_template_tool():
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("test_project_template_tool", TEMPLATE_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load project template tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProjectTemplateTests(unittest.TestCase):
    def run_tool(self, *arguments: str):
        import subprocess

        return subprocess.run(
            [sys.executable, str(TOOL), *arguments], check=False,
            capture_output=True, text=True,
        )

    def create_project(self, root: Path, name: str = "TemplateRobot") -> Path:
        created = self.run_tool("project", "create", name, "--output", str(root))
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        return root / name

    def make_legacy_v1(self, project: Path) -> None:
        template_tool = load_template_tool()
        manifest = project / "pdr-project.yaml"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document.pop("template")
        manifest.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        for relative, content in template_tool.render_template(document, 1).items():
            (project / relative).write_text(content, encoding="utf-8", newline="\n")
        (project / ".pdr/template-state.json").unlink()

    def test_new_project_records_current_template_and_clean_status(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory))
            manifest = json.loads((project / "pdr-project.yaml").read_text(encoding="utf-8"))
            self.assertEqual(manifest["template"], {"id": "pdr-product", "version": 4})
            state = json.loads((project / ".pdr/template-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["appliedVersion"], 4)
            self.assertEqual(len(state["managedFiles"]), 4)
            presets = json.loads((project / "CMakePresets.json").read_text(encoding="utf-8"))
            self.assertEqual(presets["buildPresets"][0]["configuration"], "Release")
            self.assertEqual(presets["testPresets"][0]["configuration"], "Release")
            status = self.run_tool(
                "project", "template", "status", str(project / "pdr-project.yaml"),
                "--check", "--json",
            )
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
            self.assertTrue(json.loads(status.stdout)["healthy"])

    def test_legacy_adopt_and_clean_upgrade_are_automatic(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "LegacyRobot")
            self.make_legacy_v1(project)
            manifest = project / "pdr-project.yaml"
            adopted = self.run_tool(
                "project", "template", "adopt", str(manifest), "--version", "1"
            )
            self.assertEqual(adopted.returncode, 0, adopted.stdout + adopted.stderr)
            state = json.loads((project / ".pdr/template-state.json").read_text(encoding="utf-8"))
            self.assertEqual(len(state["managedFiles"]), 4)
            self.assertEqual(state["unmanagedFiles"], [])
            before = self.run_tool(
                "project", "template", "status", str(manifest), "--check", "--json"
            )
            self.assertEqual(before.returncode, 2)
            self.assertTrue(json.loads(before.stdout)["updateAvailable"])

            upgraded = self.run_tool(
                "project", "template", "upgrade", str(manifest),
                "--report", str(project / "build/template-upgrade.json"),
            )
            self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)
            document = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(document["template"]["version"], 4)
            self.assertIn("PDR_PROJECT_TEMPLATE_VERSION 4",
                          (project / "CMakeLists.txt").read_text(encoding="utf-8"))
            self.assertIn("project template status",
                          (project / "README.md").read_text(encoding="utf-8"))
            after = self.run_tool(
                "project", "template", "status", str(manifest), "--check", "--json"
            )
            self.assertEqual(after.returncode, 0, after.stdout + after.stderr)

    def test_custom_file_requires_explicit_keep_and_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "CustomRobot")
            self.make_legacy_v1(project)
            manifest = project / "pdr-project.yaml"
            adopted = self.run_tool(
                "project", "template", "adopt", str(manifest), "--version", "1"
            )
            self.assertEqual(adopted.returncode, 0, adopted.stdout + adopted.stderr)
            cmake = project / "CMakeLists.txt"
            cmake.write_text(cmake.read_text(encoding="utf-8") + "\n# product customization\n",
                             encoding="utf-8")
            customized = cmake.read_bytes()
            report = project / "build/conflict.json"
            rejected = self.run_tool(
                "project", "template", "upgrade", str(manifest), "--report", str(report)
            )
            self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
            self.assertEqual(cmake.read_bytes(), customized)
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["template"]["version"], 1
            )
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))[
                "unresolvedConflicts"], ["CMakeLists.txt"])

            kept = self.run_tool(
                "project", "template", "upgrade", str(manifest),
                "--keep-project", "CMakeLists.txt",
            )
            self.assertEqual(kept.returncode, 0, kept.stdout + kept.stderr)
            self.assertEqual(cmake.read_bytes(), customized)
            state = json.loads((project / ".pdr/template-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["unmanagedFiles"], [{
                "path": "CMakeLists.txt", "reason": "kept-project-customization",
            }])

    def test_accept_template_replaces_drift_and_preserves_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "AcceptRobot")
            readme = project / "README.md"
            readme.write_text("custom replacement\n", encoding="utf-8")
            rejected = self.run_tool(
                "project", "template", "upgrade", str(project / "pdr-project.yaml")
            )
            self.assertEqual(rejected.returncode, 2)
            accepted = self.run_tool(
                "project", "template", "upgrade", str(project / "pdr-project.yaml"),
                "--accept-template", "README.md",
            )
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            self.assertIn("Generated PocoDDSRuntime product project",
                          readme.read_text(encoding="utf-8"))
            journals = list((project / ".pdr/template-backups").glob("*/journal.json"))
            self.assertEqual(len(journals), 1)
            journal = json.loads(journals[0].read_text(encoding="utf-8"))
            self.assertEqual(journal["status"], "completed")
            backup_entry = next(item for item in journal["entries"] if item["path"] == "README.md")
            backup = project / backup_entry["backup"]
            self.assertEqual(backup.read_text(encoding="utf-8"), "custom replacement\n")

    def test_interrupted_transaction_recovery_restores_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "RecoverTemplateRobot")
            target = project / "CMakeLists.txt"
            original = target.read_bytes()
            transaction_id = str(uuid.uuid4())
            backup_root = project / ".pdr/template-backups" / transaction_id
            backup = backup_root / "files/CMakeLists.txt"
            backup.parent.mkdir(parents=True)
            backup.write_bytes(original)
            target.write_text("partial upgrade\n", encoding="utf-8")
            journal = backup_root / "journal.json"
            journal.write_text(json.dumps({
                "schemaVersion": 1,
                "operation": "project-template-upgrade",
                "transactionId": transaction_id,
                "status": "applying",
                "startedAt": "2026-08-22T00:00:00+00:00",
                "entries": [{
                    "path": "CMakeLists.txt", "existed": True,
                    "sha256": hashlib.sha256(original).hexdigest(),
                    "backup": backup.relative_to(project).as_posix(),
                }],
                "attempted": ["CMakeLists.txt"],
            }), encoding="utf-8")
            recovered = self.run_tool(
                "project", "template", "recover", str(project / "pdr-project.yaml"),
                "--journal", str(journal),
            )
            self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(json.loads(journal.read_text(encoding="utf-8"))["status"],
                             "rolled-back")

    def test_stale_write_precondition_rejects_without_mutating_file(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "ConcurrentTemplateRobot")
            template_tool = load_template_tool()
            readme = project / "README.md"
            original = readme.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "input changed before apply"):
                template_tool.transactional_write(
                    project,
                    "project-template-upgrade",
                    {"README.md": b"must not be written"},
                    {"README.md": "0" * 64},
                )
            self.assertEqual(readme.read_bytes(), original)

    def test_status_detects_template_file_removed_from_tracking_state(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "StateGuardRobot")
            state_path = project / ".pdr/template-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["managedFiles"] = [
                item for item in state["managedFiles"] if item["path"] != "README.md"
            ]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            status = self.run_tool(
                "project", "template", "status", str(project / "pdr-project.yaml"),
                "--check", "--json",
            )
            self.assertEqual(status.returncode, 2)
            report = json.loads(status.stdout)
            readme = next(item for item in report["managedFiles"]
                          if item["path"] == "README.md")
            self.assertEqual(readme["condition"], "untracked")


if __name__ == "__main__":
    unittest.main()
