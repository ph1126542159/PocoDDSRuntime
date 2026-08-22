import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/pdr.py"


class ProjectPipelineTests(unittest.TestCase):
    def run_tool(self, *arguments: str):
        return subprocess.run(
            [sys.executable, str(TOOL), *arguments],
            check=False, capture_output=True, text=True,
        )

    def create_project(self, root: Path, profile: str = "server") -> Path:
        result = self.run_tool(
            "project", "create", "PipelineProduct", "--output", str(root),
            "--profile", profile,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return root / "PipelineProduct"

    def create_plan(self, project: Path, sdk: Path, *extra: str):
        return self.run_tool(
            "project", "pipeline", "create", str(project / "pdr-project.yaml"),
            "--sdk-prefix", str(sdk), *extra,
        )

    def test_standard_plan_is_deterministic_and_keeps_external_boundaries_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.create_project(root)
            sdk = root / "sdk"
            sdk.mkdir()
            created = self.create_plan(project, sdk)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            plan_path = project / "build/qualification/plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["metadata"]["planType"], "pdr-project-qualification")
            self.assertEqual(
                [stage["id"] for stage in plan["stages"]],
                ["validate", "resolve", "config", "configure", "build", "unit-test"],
            )
            self.assertEqual(
                plan["metadata"]["externalGates"],
                [{"id": "sil", "status": "REQUIRED",
                  "reason": "project-specific simulator evidence is not inferred"}],
            )
            for stage in plan["stages"]:
                self.assertNotIn("shell", stage)
                self.assertIsInstance(stage["command"], list)
            first = plan_path.read_bytes()
            repeated = self.create_plan(project, sdk)
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
            self.assertEqual(first, plan_path.read_bytes())

    def test_ros2_components_add_mandatory_colcon_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.create_project(root, "robotics")
            generated = self.run_tool(
                "new", "ros2-node", "MissionGateway",
                "--output", str(project / "adapters/ros2"),
            )
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            sdk = root / "sdk"
            sdk.mkdir()
            created = self.create_plan(project, sdk, "--colcon", "colcon-custom")
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            plan = json.loads((project / "build/qualification/plan.json").read_text(
                encoding="utf-8"
            ))
            ids = [stage["id"] for stage in plan["stages"]]
            self.assertEqual(ids[-3:], ["ros2-build", "ros2-test", "ros2-test-result"])
            ros_build = next(stage for stage in plan["stages"] if stage["id"] == "ros2-build")
            self.assertEqual(ros_build["command"][0], "colcon-custom")
            self.assertIn(str(project / "adapters/ros2/MissionGateway"), ros_build["command"])
            self.assertIn("ros2-build-test", plan["metadata"]["automatedGates"])

    def test_plan_rejects_unsafe_or_ambiguous_build_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.create_project(root)
            sdk = root / "sdk"
            sdk.mkdir()
            outside = root / "outside/plan.json"
            rejected = self.create_plan(
                project, sdk, "--output", str(outside), "--build-root", "build/qualification"
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("plan output must stay inside", rejected.stderr)
            rejected = self.create_plan(project, sdk, "--jobs", "0")
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("jobs must be positive", rejected.stderr)

    def test_status_never_reports_release_ready_with_pending_external_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.create_project(root)
            sdk = root / "sdk"
            sdk.mkdir()
            created = self.create_plan(project, sdk)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            plan = project / "build/qualification/plan.json"
            import hashlib
            state = project / "build/qualification/state.json"
            state.write_text(json.dumps({
                "schemaVersion": 1,
                "operation": "release-pipeline",
                "pipelineId": "pipeline-product-project-qualification",
                "status": "complete",
                "planSha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
                "stages": [{"id": "validate", "status": "passed"}],
            }), encoding="utf-8")
            status = self.run_tool(
                "project", "pipeline", "status", "--plan", str(plan),
                "--state", str(state),
            )
            self.assertEqual(status.returncode, 2, status.stdout + status.stderr)
            report = json.loads(status.stdout)
            self.assertTrue(report["automatedComplete"])
            self.assertFalse(report["releaseReady"])
            self.assertEqual(report["externalGates"][0]["id"], "sil")


if __name__ == "__main__":
    unittest.main()
