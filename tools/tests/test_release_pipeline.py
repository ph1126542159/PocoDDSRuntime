import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "release_pipeline.py"
SPEC = importlib.util.spec_from_file_location("release_pipeline_under_test", TOOL)
assert SPEC and SPEC.loader
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


class ReleasePipelineTests(unittest.TestCase):
    def test_failed_stage_resumes_and_hash_binds_completed_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, build = root / "source", root / "build"
            source.mkdir()
            build.mkdir()
            worker = source / "worker.py"
            worker.write_text("""
import pathlib, sys
mode, build = sys.argv[1], pathlib.Path(sys.argv[2])
if mode == 'first':
    (build / 'first.txt').write_text('first')
elif mode == 'retry':
    marker = build / 'retry.marker'
    if not marker.exists():
        marker.write_text('failed-once')
        raise SystemExit(7)
    (build / 'second.txt').write_text('second')
""", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=source, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=source, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=source, check=True)
            subprocess.run(["git", "add", "worker.py"], cwd=source, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source, check=True)
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "schemaVersion": 1, "pipelineId": "test-release",
                "sourceRoot": str(source), "buildRoot": str(build),
                "stages": [
                    {"id": "first", "command": [sys.executable, str(worker), "first", str(build)],
                     "requiredOutputs": ["first.txt"]},
                    {"id": "retry", "command": [sys.executable, str(worker), "retry", str(build)],
                     "requiredInputs": ["first.txt"], "requiredOutputs": ["second.txt"]},
                ],
            }), encoding="utf-8")
            state = root / "state.json"
            run = PIPELINE.parser().parse_args([
                "run", "--plan", str(plan), "--state", str(state), "--confirm-run"])
            self.assertEqual(PIPELINE.execute(run, False), 1)
            failed = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual([item["status"] for item in failed["stages"]], ["passed", "failed"])
            resume = PIPELINE.parser().parse_args([
                "resume", "--plan", str(plan), "--state", str(state), "--confirm-run"])
            self.assertEqual(PIPELINE.execute(resume, True), 0)
            complete = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(complete["status"], "complete")
            (build / "first.txt").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "output changed"):
                PIPELINE.execute(resume, True)

    def test_execution_requires_explicit_confirmation(self):
        arguments = PIPELINE.parser().parse_args([
            "run", "--plan", "missing.json", "--state", "state.json"])
        with self.assertRaisesRegex(ValueError, "confirm-run"):
            PIPELINE.execute(arguments, False)


if __name__ == "__main__":
    unittest.main()
