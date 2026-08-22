import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "pdr.py"


class ProjectConfigTests(unittest.TestCase):
    def run_tool(self, *arguments: str, environment=None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *arguments], check=False,
            capture_output=True, text=True, env=environment,
        )

    def create_project(self, root: Path) -> Path:
        result = self.run_tool("project", "create", "ConfigRobot", "--output", str(root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return root / "ConfigRobot"

    def test_layering_preserves_types_and_never_materializes_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory))
            (project / "config/base/project.json").write_text(json.dumps({
                "version": 1,
                "values": {"network": {"port": 9080, "tls": False},
                           "auth": {"token": {"$env": "PDR_PROJECT_TEST_TOKEN"}}},
            }), encoding="utf-8")
            (project / "config/site/project.json").write_text(json.dumps({
                "version": 1,
                "values": {"network": {"port": 9443, "tls": True}},
            }), encoding="utf-8")
            output = project / "build/resolved-config.json"
            environment = dict(os.environ, PDR_PROJECT_TEST_TOKEN="must-not-appear")
            result = self.run_tool(
                "project", "config", "resolve", str(project / "pdr-project.yaml"),
                "--output", str(output), "--require-environment", environment=environment,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = output.read_text(encoding="utf-8")
            self.assertNotIn("must-not-appear", text)
            resolved = json.loads(text)
            self.assertEqual(resolved["values"]["network"], {"port": 9443, "tls": True})
            self.assertEqual(resolved["environmentReferences"], ["PDR_PROJECT_TEST_TOKEN"])
            self.assertEqual(resolved["missingEnvironmentReferences"], [])

    def test_type_change_and_inline_secret_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory))
            (project / "config/base/project.json").write_text(json.dumps({
                "version": 1, "values": {"network": {"port": 9080}},
            }), encoding="utf-8")
            site = project / "config/site/project.json"
            site.write_text(json.dumps({
                "version": 1, "values": {"network": {"port": "9080"}},
            }), encoding="utf-8")
            output = project / "build/invalid.json"
            changed = self.run_tool(
                "project", "config", "resolve", str(project / "pdr-project.yaml"),
                "--output", str(output),
            )
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("configuration type changed", changed.stderr)

            site.write_text(json.dumps({
                "version": 1, "values": {"auth": {"password": "inline-secret"}},
            }), encoding="utf-8")
            secret = self.run_tool(
                "project", "config", "resolve", str(project / "pdr-project.yaml"),
                "--output", str(output),
            )
            self.assertNotEqual(secret.returncode, 0)
            self.assertIn("inline secret is prohibited", secret.stderr)

    def test_declarative_forward_migration_is_auditable(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory))
            (project / "config/base/project.json").write_text(json.dumps({
                "version": 1,
                "values": {"robot": {"controlPeriodMs": 5}},
            }), encoding="utf-8")
            migration = project / "config/migrations/v1-to-v2.json"
            migration.write_text(json.dumps({
                "from": 1, "to": 2,
                "operations": [
                    {"op": "rename", "from": "robot.controlPeriodMs",
                     "path": "robot.control_period_ms"},
                    {"op": "set-default", "path": "robot.watchdog.enabled", "value": True},
                ],
            }), encoding="utf-8")
            output = project / "build/resolved-v2.json"
            result = self.run_tool(
                "project", "config", "resolve", str(project / "pdr-project.yaml"),
                "--output", str(output), "--target-version", "2",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            resolved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(resolved["configVersion"], 2)
            self.assertEqual(resolved["values"]["robot"]["control_period_ms"], 5)
            self.assertTrue(resolved["values"]["robot"]["watchdog"]["enabled"])
            self.assertEqual(resolved["migrations"][0]["path"],
                             "config/migrations/v1-to-v2.json")


if __name__ == "__main__":
    unittest.main()
