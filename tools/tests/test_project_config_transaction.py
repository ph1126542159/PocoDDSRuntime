import importlib.util
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
TOOL = TOOLS / "pdr.py"
TRANSACTION_TOOL = TOOLS / "project_config_transaction.py"


def load_transaction_tool():
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("test_project_config_transaction_tool",
                                                  TRANSACTION_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load project configuration transaction tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProjectConfigTransactionTests(unittest.TestCase):
    def run_tool(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *arguments], check=False,
            capture_output=True, text=True,
        )

    def create_project(self, root: Path, name: str = "TransactionRobot") -> Path:
        result = self.run_tool(
            "project", "create", name, "--output", str(root), "--profile", "robotics"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        project = root / name
        agent = project / "config/transaction-agent.py"
        agent.write_text(
            """import json
import sys
from pathlib import Path

request = json.load(sys.stdin)
log = Path(sys.argv[1])
log.parent.mkdir(parents=True, exist_ok=True)
with log.open("a", encoding="utf-8") as stream:
    stream.write(request["participant"] + ":" + request["phase"] + "\\n")
if request["phase"] == "commit" and request["participant"] == sys.argv[2]:
    raise SystemExit(9)
status = {"preflight": "ready", "commit": "committed", "rollback": "rolled-back"}
print(json.dumps({
    "schemaVersion": 1,
    "transactionId": request["transactionId"],
    "participant": request["participant"],
    "status": status[request["phase"]],
}))
""",
            encoding="utf-8",
        )
        return project

    def configure_participants(self, project: Path, fail: str = "-") -> None:
        command = [sys.executable, "config/transaction-agent.py", "build/agent.log", fail]
        (project / "config/capabilities.json").write_text(json.dumps({
            "schemaVersion": 1,
            "participants": [
                {
                    "id": "network-service", "ownedPaths": ["/network"],
                    "mode": "hot-reload", "after": [], "timeoutSeconds": 5,
                    "command": command,
                },
                {
                    "id": "feature-service", "ownedPaths": ["/feature"],
                    "mode": "hot-reload", "after": ["network-service"],
                    "timeoutSeconds": 5, "command": command,
                },
            ],
        }, indent=2), encoding="utf-8")

    def resolve_pair(self, project: Path) -> tuple[Path, Path]:
        manifest = project / "pdr-project.yaml"
        current = project / "build/current.json"
        candidate = project / "build/candidate.json"
        baseline = self.run_tool(
            "project", "config", "resolve", str(manifest), "--output", str(current)
        )
        self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
        (project / "config/site/project.json").write_text(json.dumps({
            "version": 1,
            "values": {
                "network": {"port": 9443},
                "feature": {"enabled": True},
            },
        }), encoding="utf-8")
        changed = self.run_tool(
            "project", "config", "resolve", str(manifest), "--output", str(candidate)
        )
        self.assertEqual(changed.returncode, 0, changed.stdout + changed.stderr)
        return current, candidate

    def plan(self, project: Path, current: Path, candidate: Path) -> tuple[Path, dict]:
        plan = project / "build/config-plan.json"
        result = self.run_tool(
            "project", "config", "plan", str(project / "pdr-project.yaml"),
            "--current", str(current), "--candidate", str(candidate), "--output", str(plan),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return plan, json.loads(plan.read_text(encoding="utf-8"))

    def test_preflight_commit_order_and_atomic_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory))
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            plan_path, plan = self.plan(project, current, candidate)
            self.assertEqual(
                [item["id"] for item in plan["participants"]],
                ["network-service", "feature-service"],
            )
            result = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(current.read_bytes(), candidate.read_bytes())
            self.assertEqual(
                (project / "build/agent.log").read_text(encoding="utf-8").splitlines(),
                [
                    "network-service:preflight", "feature-service:preflight",
                    "network-service:commit", "feature-service:commit",
                ],
            )
            journal = json.loads(next(
                (project / "build/config-transactions").glob("*.journal.json")
            ).read_text(encoding="utf-8"))
            self.assertEqual(journal["status"], "committed")
            self.assertEqual(journal["commitCompleted"],
                             ["network-service", "feature-service"])

    def test_commit_failure_rolls_back_attempted_participants_in_reverse(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "RollbackRobot")
            self.configure_participants(project, fail="feature-service")
            current, candidate = self.resolve_pair(project)
            previous = current.read_bytes()
            plan_path, _ = self.plan(project, current, candidate)
            result = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(current.read_bytes(), previous)
            self.assertEqual(
                (project / "build/agent.log").read_text(encoding="utf-8").splitlines(),
                [
                    "network-service:preflight", "feature-service:preflight",
                    "network-service:commit", "feature-service:commit",
                    "feature-service:rollback", "network-service:rollback",
                ],
            )
            journal = json.loads(next(
                (project / "build/config-transactions").glob("*.journal.json")
            ).read_text(encoding="utf-8"))
            self.assertEqual(journal["status"], "rolled-back")
            self.assertEqual(journal["commitAttempted"],
                             ["network-service", "feature-service"])

    def test_tampered_plan_cannot_skip_an_affected_participant(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "PlanGuardRobot")
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            previous = current.read_bytes()
            plan_path, plan = self.plan(project, current, candidate)
            plan["participants"] = plan["participants"][:1]
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            result = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("plan semantics mismatch", result.stderr)
            self.assertEqual(current.read_bytes(), previous)
            self.assertFalse((project / "build/agent.log").exists())

    def test_immutable_and_unowned_changes_are_rejected_during_planning(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "PolicyRobot")
            (project / "config/capabilities.json").write_text(json.dumps({
                "schemaVersion": 1,
                "participants": [{
                    "id": "robot-core", "ownedPaths": ["/robot"],
                    "mode": "immutable", "after": [], "timeoutSeconds": 5,
                }],
            }), encoding="utf-8")
            current, candidate = self.resolve_pair(project)
            plan = project / "build/rejected-plan.json"
            result = self.run_tool(
                "project", "config", "plan", str(project / "pdr-project.yaml"),
                "--current", str(current), "--candidate", str(candidate),
                "--output", str(plan),
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            evidence = json.loads(plan.read_text(encoding="utf-8"))
            self.assertFalse(evidence["applicable"])
            self.assertEqual(evidence["rejectionReasons"], ["UNOWNED_CONFIGURATION_PATH"])

            candidate_document = json.loads(candidate.read_text(encoding="utf-8"))
            candidate_document["values"]["robot"]["controlPeriodMs"] = 7
            transaction = load_transaction_tool()
            candidate_document["valuesSha256"] = transaction.digest(candidate_document["values"])
            candidate.write_text(json.dumps(candidate_document), encoding="utf-8")
            result = self.run_tool(
                "project", "config", "plan", str(project / "pdr-project.yaml"),
                "--current", str(current), "--candidate", str(candidate),
                "--output", str(plan),
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            reasons = json.loads(plan.read_text(encoding="utf-8"))["rejectionReasons"]
            self.assertEqual(reasons,
                             ["IMMUTABLE_CONFIGURATION_CHANGED", "UNOWNED_CONFIGURATION_PATH"])

    def test_recovery_uses_attempt_journal_and_restores_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "RecoveryRobot")
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            plan_path, plan = self.plan(project, current, candidate)
            transaction = load_transaction_tool()
            manifest = project / "pdr-project.yaml"
            capabilities, _, capability_path = transaction.load_capabilities(manifest)
            current_document = json.loads(current.read_text(encoding="utf-8"))
            state = project / "build/config-transactions"
            state.mkdir(parents=True)
            previous = state / f"{plan['transactionId']}.previous-config.json"
            shutil.copyfile(current, previous)
            shutil.copyfile(candidate, current)
            journal = state / f"{plan['transactionId']}.journal.json"
            journal.write_text(json.dumps({
                "schemaVersion": 1,
                "operation": "project-config-transaction",
                "transactionId": plan["transactionId"],
                "project": "recovery-robot",
                "status": "activating",
                "manifest": "pdr-project.yaml",
                "manifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "plan": plan_path.relative_to(project).as_posix(),
                "planSha256": transaction.digest(plan),
                "capabilities": capability_path.relative_to(project).as_posix(),
                "capabilitiesSha256": transaction.digest(capabilities),
                "currentConfig": current.relative_to(project).as_posix(),
                "candidateConfig": candidate.relative_to(project).as_posix(),
                "previousConfig": previous.relative_to(project).as_posix(),
                "previousConfigSha256": transaction.digest(current_document),
                "preflightCompleted": ["network-service", "feature-service"],
                "commitAttempted": ["network-service", "feature-service"],
                "commitCompleted": ["network-service", "feature-service"],
                "rollbackCompleted": [],
                "events": [],
                "errors": [],
            }), encoding="utf-8")
            result = self.run_tool(
                "project", "config", "recover", str(manifest), "--journal", str(journal)
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads(current.read_text(encoding="utf-8"))["valuesSha256"],
                current_document["valuesSha256"],
            )
            self.assertEqual(
                (project / "build/agent.log").read_text(encoding="utf-8").splitlines(),
                ["feature-service:rollback", "network-service:rollback"],
            )
            self.assertEqual(json.loads(journal.read_text(encoding="utf-8"))["status"],
                             "rolled-back")


if __name__ == "__main__":
    unittest.main()
