import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
TOOL = TOOLS / "pdr.py"
FINGERPRINTS = ROOT / "contracts/component-templates/v1.json"


def load_tool(path: Path, module_name: str):
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load tool: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PDR = load_tool(TOOL, "component_template_test_pdr")
COMPONENT_TEMPLATE = load_tool(TOOLS / "component_template.py", "component_template_test_tool")


class ComponentTemplateTests(unittest.TestCase):
    def run_tool(self, *arguments: str):
        return subprocess.run(
            [sys.executable, str(TOOL), *arguments],
            check=False, capture_output=True, text=True,
        )

    def create(self, root: Path, kind: str = "service", name: str = "TemplateService") -> Path:
        result = self.run_tool(
            "new", kind, name, "--output", str(root), "--no-register"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return root / name

    def make_legacy_v1(self, root: Path, kind: str, name: str) -> Path:
        component = root / name
        component.mkdir(parents=True)
        for relative, content in PDR.templates(kind, name).items():
            path = component / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        return component

    def test_frozen_v1_fingerprints_cover_every_kind(self):
        contract = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
        self.assertEqual(set(contract["fingerprints"]), set(PDR.KINDS))
        self.assertEqual(contract["probeName"], "TemplateProbe")
        for kind in PDR.KINDS:
            actual = COMPONENT_TEMPLATE.baseline_fingerprint(kind, PDR.templates)
            self.assertEqual(actual, contract["fingerprints"][kind], kind)

    def test_every_generated_kind_is_current_and_business_files_are_product_owned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, kind in enumerate(PDR.KINDS):
                name = f"TemplateKind{index}"
                component = self.create(root, kind, name)
                state = json.loads((component / ".pdr-component.json").read_text(
                    encoding="utf-8"
                ))
                self.assertEqual(state["kind"], kind)
                self.assertEqual(state["appliedVersion"], 2)
                self.assertTrue(state["managedFiles"])
                cmake = component / "CMakeLists.txt"
                self.assertIn("PDR_COMPONENT_TEMPLATE_VERSION 2",
                              cmake.read_text(encoding="utf-8"))

                project_file = state["projectFiles"][0]["path"]
                project_path = component / project_file
                project_path.write_text(
                    project_path.read_text(encoding="utf-8") + "\n// product change\n",
                    encoding="utf-8",
                )
                status = self.run_tool(
                    "component", "status", str(component), "--check", "--json"
                )
                self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
                report = json.loads(status.stdout)
                self.assertTrue(report["healthy"])
                record = next(item for item in report["projectFiles"]
                              if item["path"] == project_file)
                self.assertEqual(record["condition"], "product-owned")

    def test_managed_drift_and_removed_tracking_record_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            component = self.create(Path(directory))
            cmake = component / "CMakeLists.txt"
            cmake.write_text(cmake.read_text(encoding="utf-8") + "\n# drift\n",
                             encoding="utf-8")
            status = self.run_tool(
                "component", "status", str(component), "--check", "--json"
            )
            self.assertEqual(status.returncode, 2)
            self.assertTrue(json.loads(status.stdout)["drifted"])
            verified = self.run_tool("verify", str(component))
            self.assertNotEqual(verified.returncode, 0)
            self.assertIn("managed files drifted", verified.stderr)

            state_path = component / ".pdr-component.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["managedFiles"] = [
                item for item in state["managedFiles"] if item["path"] != "README.md"
            ]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            verified = self.run_tool("verify", str(component))
            self.assertNotEqual(verified.returncode, 0)
            self.assertIn("untracked=README.md", verified.stderr)

    def test_legacy_adopt_and_upgrade_never_touch_business_source(self):
        with tempfile.TemporaryDirectory() as directory:
            component = self.make_legacy_v1(Path(directory), "service", "LegacyService")
            source = component / "src/LegacyService.cpp"
            source.write_text(source.read_text(encoding="utf-8") + "\n// customer logic\n",
                              encoding="utf-8")
            custom_source = source.read_bytes()
            adopted = self.run_tool(
                "component", "adopt", str(component), "--kind", "service",
                "--name", "LegacyService", "--version", "1",
            )
            self.assertEqual(adopted.returncode, 0, adopted.stdout + adopted.stderr)
            before = self.run_tool(
                "component", "status", str(component), "--check", "--json"
            )
            self.assertEqual(before.returncode, 2)
            self.assertTrue(json.loads(before.stdout)["updateAvailable"])
            upgraded = self.run_tool("component", "upgrade", str(component))
            self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)
            self.assertEqual(source.read_bytes(), custom_source)
            self.assertIn("PDR_COMPONENT_TEMPLATE_VERSION 2",
                          (component / "CMakeLists.txt").read_text(encoding="utf-8"))
            after = self.run_tool(
                "component", "status", str(component), "--check", "--json"
            )
            self.assertEqual(after.returncode, 0, after.stdout + after.stderr)

    def test_managed_conflict_requires_keep_or_accept_and_backup_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            component = self.make_legacy_v1(Path(directory), "bundle", "LegacyBundle")
            adopted = self.run_tool(
                "component", "adopt", str(component), "--kind", "bundle",
                "--name", "LegacyBundle", "--version", "1",
            )
            self.assertEqual(adopted.returncode, 0, adopted.stdout + adopted.stderr)
            readme = component / "README.md"
            readme.write_text("product documentation\n", encoding="utf-8")
            custom = readme.read_bytes()
            rejected = self.run_tool("component", "upgrade", str(component))
            self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
            self.assertEqual(readme.read_bytes(), custom)
            kept = self.run_tool(
                "component", "upgrade", str(component), "--keep-project", "README.md"
            )
            self.assertEqual(kept.returncode, 0, kept.stdout + kept.stderr)
            self.assertEqual(readme.read_bytes(), custom)
            state = json.loads((component / ".pdr-component.json").read_text(
                encoding="utf-8"
            ))
            self.assertIn(
                {"path": "README.md", "reason": "kept-product-customization"},
                state["unmanagedFiles"],
            )

            accepted_component = self.create(Path(directory), "service", "AcceptService")
            accepted_readme = accepted_component / "README.md"
            accepted_readme.write_text("replace me\n", encoding="utf-8")
            accepted = self.run_tool(
                "component", "upgrade", str(accepted_component),
                "--accept-template", "README.md",
            )
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            journals = list((accepted_component / ".pdr/template-backups").glob("*/journal.json"))
            self.assertEqual(len(journals), 1)
            journal = json.loads(journals[0].read_text(encoding="utf-8"))
            entry = next(item for item in journal["entries"] if item["path"] == "README.md")
            self.assertEqual(
                (accepted_component / entry["backup"]).read_text(encoding="utf-8"),
                "replace me\n",
            )

    def test_interrupted_upgrade_can_be_rolled_back(self):
        with tempfile.TemporaryDirectory() as directory:
            component = self.create(Path(directory), "module", "RecoverModule")
            target = component / "CMakeLists.txt"
            original = target.read_bytes()
            transaction_id = str(uuid.uuid4())
            backup_root = component / ".pdr/template-backups" / transaction_id
            backup = backup_root / "files/CMakeLists.txt"
            backup.parent.mkdir(parents=True)
            backup.write_bytes(original)
            target.write_text("partial component upgrade\n", encoding="utf-8")
            journal = backup_root / "journal.json"
            journal.write_text(json.dumps({
                "schemaVersion": 1,
                "operation": "component-template-upgrade",
                "transactionId": transaction_id,
                "status": "applying",
                "startedAt": "2026-08-22T00:00:00+00:00",
                "entries": [{
                    "path": "CMakeLists.txt", "existed": True,
                    "sha256": hashlib.sha256(original).hexdigest(),
                    "backup": backup.relative_to(component).as_posix(),
                }],
                "attempted": ["CMakeLists.txt"],
            }), encoding="utf-8")
            recovered = self.run_tool(
                "component", "recover", str(component), "--journal", str(journal)
            )
            self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(json.loads(journal.read_text(encoding="utf-8"))["status"],
                             "rolled-back")

    def test_project_validation_rejects_drifted_registered_component(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = self.run_tool("project", "create", "GovernedRobot", "--output", str(root))
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            project = root / "GovernedRobot"
            generated = self.run_tool(
                "new", "service", "GovernedService",
                "--output", str(project / "components"),
            )
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            manifest = project / "pdr-project.yaml"
            valid = self.run_tool("project", "validate", str(manifest))
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
            cmake = project / "components/GovernedService/CMakeLists.txt"
            cmake.write_text(cmake.read_text(encoding="utf-8") + "\n# release drift\n",
                             encoding="utf-8")
            rejected = self.run_tool("project", "validate", str(manifest))
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("managed files drifted", rejected.stdout + rejected.stderr)


if __name__ == "__main__":
    unittest.main()
