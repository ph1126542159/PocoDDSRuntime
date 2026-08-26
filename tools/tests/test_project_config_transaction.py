import contextlib
import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parent
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
        values = list(arguments)
        if (values[:3] in (["project", "config", "apply"],
                           ["project", "config", "recover"])
                and "--actor" not in values):
            values.extend(["--actor", "test-operator"])
        return subprocess.run(
            [sys.executable, str(TOOL), *values], check=False,
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

    def configure_approval_policy(self, project: Path) -> tuple[Path, Path, dict[str, Path]]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        trusted_keys = project.parent / "trusted-config-keys"
        private_keys = project.parent / "private-config-keys"
        trusted_keys.mkdir()
        private_keys.mkdir()
        identities = (
            ("alice", "alice-key", "security"),
            ("bob", "bob-key", "operations"),
            ("carol", "carol-key", "security"),
        )
        private: dict[str, Path] = {}
        approvers = []
        for approver_id, key_id, role in identities:
            key = Ed25519PrivateKey.generate()
            private_path = private_keys / f"{key_id}.pem"
            public_path = trusted_keys / f"{key_id}.pem"
            private_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
            public_path.write_bytes(key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
            private[approver_id] = private_path
            approvers.append({
                "approverId": approver_id,
                "keyId": key_id,
                "role": role,
                "algorithm": "Ed25519",
                "publicKeySha256": hashlib.sha256(public_path.read_bytes()).hexdigest(),
                "ruleIds": ["network-production"],
            })
        policy = project / "config/approval-policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeProjectConfiguration",
            "policyId": "production-config-v1",
            "maxApprovalLifetimeSeconds": 3600,
            "rules": [{
                "id": "network-production",
                "pathPrefixes": ["/network"],
                "minimumApprovals": 2,
                "requiredRoles": ["security", "operations"],
                "separateInitiator": True,
            }],
            "allowedApprovers": approvers,
            "revokedKeys": [],
        }, indent=2), encoding="utf-8")
        manifest = project / "pdr-project.yaml"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["config"]["approvalPolicy"] = "config/approval-policy.json"
        manifest.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return policy, trusted_keys, private

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
            self.assertEqual(journal["schemaVersion"], 3)
            self.assertEqual(journal["initiatedBy"], "test-operator")
            transaction = load_transaction_tool()
            self.assertEqual(
                journal["journalSha256"],
                transaction.self_digest(journal, "journalSha256"),
            )
            self.assertEqual(journal["commitCompleted"],
                             ["network-service", "feature-service"])

    def test_collaboration_status_reports_ready_busy_invalid_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "StatusRobot")
            self.configure_participants(project)
            manifest = project / "pdr-project.yaml"
            state = project / "build/config-transactions"

            empty = self.run_tool(
                "project", "config", "status", str(manifest), "--json", "--check"
            )
            self.assertEqual(empty.returncode, 0, empty.stdout + empty.stderr)
            empty_report = json.loads(empty.stdout)
            self.assertEqual(empty_report["overallStatus"], "ready")
            self.assertTrue(empty_report["canApply"])
            self.assertEqual(empty_report["audit"]["status"], "empty")

            current, candidate = self.resolve_pair(project)
            plan_path, _ = self.plan(project, current, candidate)
            applied = self.run_tool(
                "project", "config", "apply", str(manifest),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate), "--actor", "status-owner",
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            report_path = project / "build/config-status.json"
            healthy = self.run_tool(
                "project", "config", "status", str(manifest), "--json", "--check",
                "--report", str(report_path),
            )
            self.assertEqual(healthy.returncode, 0, healthy.stdout + healthy.stderr)
            healthy_report = json.loads(healthy.stdout)
            self.assertEqual(healthy_report["overallStatus"], "ready")
            self.assertEqual(healthy_report["audit"]["status"], "valid")
            self.assertEqual(healthy_report["transactions"]["terminal"], 1)
            self.assertEqual(
                healthy_report["transactions"]["items"][0]["initiatedBy"],
                "status-owner",
            )
            self.assertEqual(json.loads(report_path.read_text(
                encoding="utf-8"))["operation"], "project-config-transaction-status")

            lock_path = state / "config-transaction.lock"
            lock_path.write_text(json.dumps({
                "pid": os.getpid(),
                "transactionId": str(uuid.uuid4()),
                "actor": "active-owner",
            }), encoding="utf-8")
            busy = self.run_tool(
                "project", "config", "status", str(manifest), "--json", "--check"
            )
            self.assertEqual(busy.returncode, 2, busy.stdout + busy.stderr)
            busy_report = json.loads(busy.stdout)
            self.assertEqual(busy_report["overallStatus"], "busy")
            self.assertEqual(busy_report["lock"]["actor"], "active-owner")
            lock_path.unlink()

            lock_path.write_text(json.dumps({
                "pid": os.getpid(),
                "transactionId": str(uuid.uuid4()),
                "processIdentity": "win-filetime:1",
                "actor": "reused-pid-owner",
            }), encoding="utf-8")
            reused = self.run_tool(
                "project", "config", "status", str(manifest), "--json", "--check"
            )
            self.assertEqual(reused.returncode, 0, reused.stdout + reused.stderr)
            reused_report = json.loads(reused.stdout)
            self.assertEqual(reused_report["lock"]["status"], "stale")
            lock_path.unlink()

            lock_path.write_text(json.dumps({
                "pid": 2147483647,
                "transactionId": str(uuid.uuid4()),
                "actor": "previous-owner",
            }), encoding="utf-8")
            stale = self.run_tool(
                "project", "config", "status", str(manifest), "--json", "--check"
            )
            self.assertEqual(stale.returncode, 0, stale.stdout + stale.stderr)
            stale_report = json.loads(stale.stdout)
            self.assertEqual(stale_report["overallStatus"], "ready")
            self.assertEqual(stale_report["lock"]["status"], "stale")
            lock_path.unlink()

            audit_path = state / "config-transaction-audit.jsonl"
            head_path = state / "config-transaction-audit.head.json"
            audit_bytes = audit_path.read_bytes()
            head_bytes = head_path.read_bytes()
            audit_record = json.loads(audit_bytes)
            audit_record["actor"] = "tampered-owner"
            audit_path.write_text(json.dumps(audit_record) + "\n", encoding="utf-8")
            invalid = self.run_tool(
                "project", "config", "status", str(manifest), "--json", "--check"
            )
            self.assertEqual(invalid.returncode, 2, invalid.stdout + invalid.stderr)
            invalid_report = json.loads(invalid.stdout)
            self.assertEqual(invalid_report["overallStatus"], "invalid")
            self.assertEqual(invalid_report["audit"]["status"], "invalid")
            audit_path.write_bytes(audit_bytes)
            head_path.write_bytes(head_bytes)

            journal_path = next(state.glob("*.journal.json"))
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            journal["status"] = "activating"
            for field in (
                    "finishedAt", "activeConfigSha256", "auditSequence",
                    "auditRecordSha256", "auditEvent"):
                journal.pop(field, None)
            transaction = load_transaction_tool()
            transaction.write_journal(journal_path, journal)
            audit_path.unlink()
            head_path.unlink()
            recovery = self.run_tool(
                "project", "config", "status", str(manifest), "--json", "--check"
            )
            self.assertEqual(recovery.returncode, 2, recovery.stdout + recovery.stderr)
            recovery_report = json.loads(recovery.stdout)
            self.assertEqual(recovery_report["overallStatus"], "recovery-required")
            self.assertFalse(recovery_report["canApply"])
            self.assertEqual(recovery_report["transactions"]["recoveryRequired"], 1)
            self.assertEqual(
                recovery_report["transactions"]["items"][0]["initiatedBy"],
                "status-owner",
            )

    def test_process_liveness_probe_does_not_signal_the_process(self):
        transaction = load_transaction_tool()
        child = subprocess.Popen([
            sys.executable, "-c", "import time; time.sleep(30)"
        ])
        try:
            self.assertTrue(transaction.process_alive(child.pid))
            self.assertIsNotNone(transaction.process_identity(child.pid))
            self.assertIsNone(child.poll())
        finally:
            child.terminate()
            child.wait(timeout=10)

    def test_preflight_evidence_is_non_mutating_bound_and_rechecked_on_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "PreflightRobot")
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            previous = current.read_bytes()
            plan_path, _ = self.plan(project, current, candidate)
            evidence_path = project / "build/config-preflight.json"
            result = self.run_tool(
                "project", "config", "preflight", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate), "--output", str(evidence_path),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(current.read_bytes(), previous)
            evidence_bytes = evidence_path.read_bytes()
            evidence = json.loads(evidence_bytes)
            transaction = load_transaction_tool()
            self.assertEqual(evidence["status"], "passed")
            self.assertEqual(
                evidence["evidenceSha256"],
                transaction.self_digest(evidence, "evidenceSha256"),
            )
            self.assertEqual(
                (project / "build/agent.log").read_text(encoding="utf-8").splitlines(),
                ["network-service:preflight", "feature-service:preflight"],
            )

            evidence["participants"].reverse()
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            rejected = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate), "--preflight-evidence", str(evidence_path),
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("preflight evidence hash mismatch", rejected.stderr)
            self.assertEqual(current.read_bytes(), previous)
            evidence_path.write_bytes(evidence_bytes)

            applied = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate), "--preflight-evidence", str(evidence_path),
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            self.assertEqual(current.read_bytes(), candidate.read_bytes())
            self.assertEqual(
                (project / "build/agent.log").read_text(encoding="utf-8").splitlines(),
                [
                    "network-service:preflight", "feature-service:preflight",
                    "network-service:preflight", "feature-service:preflight",
                    "network-service:commit", "feature-service:commit",
                ],
            )
            journal = json.loads(next(
                (project / "build/config-transactions").glob("*.journal.json")
            ).read_text(encoding="utf-8"))
            self.assertEqual(journal["preflightEvidence"], "build/config-preflight.json")
            self.assertEqual(
                journal["preflightEvidenceSha256"],
                json.loads(evidence_bytes)["evidenceSha256"],
            )

    def test_unfinished_transaction_blocks_a_new_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "TransactionGuardRobot")
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            plan_path, plan = self.plan(project, current, candidate)
            state = project / "build/config-transactions"
            state.mkdir(parents=True)
            pending_id = str(uuid.uuid4())
            (state / f"{pending_id}.journal.json").write_text(json.dumps({
                "schemaVersion": 1,
                "operation": "project-config-transaction",
                "transactionId": pending_id,
                "project": plan["project"],
                "status": "committing",
                "preflightCompleted": [],
                "commitAttempted": [],
                "commitCompleted": [],
                "rollbackCompleted": [],
                "events": [],
                "errors": [],
            }), encoding="utf-8")
            previous = current.read_bytes()
            result = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unfinished configuration transaction requires recovery", result.stderr)
            self.assertEqual(current.read_bytes(), previous)
            self.assertFalse((project / "build/agent.log").exists())

    def test_apply_rejects_input_drift_while_acquiring_the_global_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "LockDriftRobot")
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            plan_path, _ = self.plan(project, current, candidate)
            previous = current.read_bytes()
            transaction = load_transaction_tool()
            original_lock = transaction.transaction_lock

            @contextlib.contextmanager
            def drifting_lock(state, transaction_id, actor=None):
                document = json.loads(candidate.read_text(encoding="utf-8"))
                document["values"]["network"]["port"] = 9555
                document["valuesSha256"] = transaction.digest(document["values"])
                candidate.write_text(json.dumps(document), encoding="utf-8")
                with original_lock(state, transaction_id, actor):
                    yield

            arguments = SimpleNamespace(
                manifest=str(project / "pdr-project.yaml"),
                plan=str(plan_path), current=str(current), candidate=str(candidate),
                state_dir="build/config-transactions", preflight_evidence=None,
                allow_restart=False, actor="test-operator",
            )
            with mock.patch.object(transaction, "transaction_lock", drifting_lock):
                with self.assertRaisesRegex(
                        ValueError, "candidate configuration changed while acquiring the lock"):
                    transaction.apply_command(arguments)
            self.assertEqual(current.read_bytes(), previous)
            self.assertFalse((project / "build/agent.log").exists())

    def test_high_risk_apply_requires_distinct_roles_and_initiator_separation(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "ApprovalRobot")
            self.configure_participants(project)
            policy, trusted_keys, private = self.configure_approval_policy(project)
            current, candidate = self.resolve_pair(project)
            plan_path, plan = self.plan(project, current, candidate)
            self.assertTrue(plan["approval"]["required"])
            self.assertEqual(
                plan["approval"]["rules"][0]["requiredRoles"],
                ["operations", "security"],
            )
            verifier = ROOT / "build/bin/pdr-signature-check.exe"
            self.assertTrue(verifier.is_file(), verifier)
            policy_sha = hashlib.sha256(policy.read_bytes()).hexdigest()

            def sign_request(request_path: Path, approver_id: str,
                             key_id: str, suffix: str) -> Path:
                output = project / f"build/{approver_id}-{suffix}.signature.json"
                environment_name = f"PDR_TEST_CONFIG_APPROVAL_{approver_id.upper()}"
                with mock.patch.dict(os.environ, {environment_name: str(private[approver_id])}):
                    signed = self.run_tool(
                        "project", "config", "approve",
                        "--request", str(request_path),
                        "--approver-id", approver_id, "--key-id", key_id,
                        "--private-key-path-environment", environment_name,
                        "--signature-output", str(output),
                    )
                self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)
                return output

            no_approval = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate),
            )
            self.assertNotEqual(no_approval.returncode, 0)
            self.assertIn("requires signed approval arguments", no_approval.stderr)

            self_request = project / "build/approval-self.json"
            created_self = self.run_tool(
                "project", "config", "approval-request",
                str(project / "pdr-project.yaml"), "--plan", str(plan_path),
                "--ticket", "CHANGE-41", "--initiator", "alice",
                "--output", str(self_request),
            )
            self.assertEqual(
                created_self.returncode, 0, created_self.stdout + created_self.stderr
            )
            self_alice = sign_request(self_request, "alice", "alice-key", "self")
            self_bob = sign_request(self_request, "bob", "bob-key", "self")
            self_common = (
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate),
                "--approval-request", str(self_request),
                "--approval-policy", str(policy),
                "--expected-approval-policy-id", "production-config-v1",
                "--expected-approval-policy-sha256", policy_sha,
                "--approval-trusted-keys-directory", str(trusted_keys),
                "--signature-check-executable", str(verifier),
                "--approval-signature", str(self_alice),
                "--approval-signature", str(self_bob),
            )
            self_approval = self.run_tool(*self_common)
            self.assertNotEqual(self_approval.returncode, 0)
            self.assertIn("requires initiator separation", self_approval.stderr)

            separated_request = project / "build/approval-separated.json"
            request = self.run_tool(
                "project", "config", "approval-request",
                str(project / "pdr-project.yaml"), "--plan", str(plan_path),
                "--ticket", "CHANGE-42", "--initiator", "requester",
                "--output", str(separated_request),
            )
            self.assertEqual(request.returncode, 0, request.stdout + request.stderr)

            signatures: dict[str, Path] = {}
            for approver_id, key_id in (
                    ("alice", "alice-key"), ("bob", "bob-key"), ("carol", "carol-key")):
                signatures[approver_id] = sign_request(
                    separated_request, approver_id, key_id, "separated"
                )

            common = (
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate),
                "--approval-request", str(separated_request),
                "--approval-policy", str(policy),
                "--expected-approval-policy-id", "production-config-v1",
                "--expected-approval-policy-sha256", policy_sha,
                "--approval-trusted-keys-directory", str(trusted_keys),
                "--signature-check-executable", str(verifier),
            )
            one_person = self.run_tool(
                *common, "--approval-signature", str(signatures["alice"])
            )
            self.assertNotEqual(one_person.returncode, 0)
            self.assertIn("quorum not met", one_person.stderr)

            wrong_roles = self.run_tool(
                *common,
                "--approval-signature", str(signatures["alice"]),
                "--approval-signature", str(signatures["carol"]),
            )
            self.assertNotEqual(wrong_roles.returncode, 0)
            self.assertIn("roles missing", wrong_roles.stderr)
            self.assertFalse((project / "build/agent.log").exists())

            applied = self.run_tool(
                *common,
                "--approval-signature", str(signatures["alice"]),
                "--approval-signature", str(signatures["bob"]),
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            journal = json.loads(next(
                (project / "build/config-transactions").glob("*.journal.json")
            ).read_text(encoding="utf-8"))
            self.assertEqual(journal["approval"]["ticket"], "CHANGE-42")
            self.assertEqual(
                {item["role"] for item in journal["approval"]["approvals"]},
                {"security", "operations"},
            )

    def test_production_gate_rejects_a_plan_without_an_approval_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "PolicyRequiredRobot")
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            plan_path, plan = self.plan(project, current, candidate)
            self.assertIsNone(plan["approval"]["policy"])
            result = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate), "--require-approval-policy",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires pinned approval policy arguments", result.stderr)
            self.assertFalse((project / "build/agent.log").exists())

    def test_production_gate_allows_low_risk_apply_without_signatures(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "LowRiskPolicyRobot")
            self.configure_participants(project)
            policy, _, _ = self.configure_approval_policy(project)
            document = json.loads(policy.read_text(encoding="utf-8"))
            document["rules"][0]["pathPrefixes"] = ["/robot/safety"]
            policy.write_text(json.dumps(document, indent=2), encoding="utf-8")
            current, candidate = self.resolve_pair(project)
            plan_path, plan = self.plan(project, current, candidate)
            self.assertFalse(plan["approval"]["required"])
            self.assertIsNotNone(plan["approval"]["policy"])
            policy_sha = hashlib.sha256(policy.read_bytes()).hexdigest()
            result = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate), "--require-approval-policy",
                "--approval-policy", str(policy),
                "--expected-approval-policy-id", "production-config-v1",
                "--expected-approval-policy-sha256", policy_sha,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(current.read_bytes(), candidate.read_bytes())

    def test_audit_chain_detects_record_and_tail_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "AuditRobot")
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            first_plan, _ = self.plan(project, current, candidate)
            first = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(first_plan), "--current", str(current),
                "--candidate", str(candidate),
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

            site = project / "config/site/project.json"
            site.write_text(json.dumps({
                "version": 1,
                "values": {
                    "network": {"port": 9555},
                    "feature": {"enabled": False},
                },
            }), encoding="utf-8")
            candidate2 = project / "build/candidate-2.json"
            resolved = self.run_tool(
                "project", "config", "resolve", str(project / "pdr-project.yaml"),
                "--output", str(candidate2),
            )
            self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)
            second_plan, _ = self.plan(project, current, candidate2)
            second = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(second_plan), "--current", str(current),
                "--candidate", str(candidate2),
            )
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

            state = project / "build/config-transactions"
            report = project / "build/config-audit-report.json"
            verified = self.run_tool(
                "project", "config", "verify-audit", "--state-dir", str(state),
                "--report", str(report),
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["recordCount"], 2)

            audit = state / "config-transaction-audit.jsonl"
            original = audit.read_bytes()
            lines = original.splitlines(keepends=True)
            tampered = json.loads(lines[0])
            tampered["actor"] = "different-operator"
            lines[0] = json.dumps(tampered).encode("utf-8") + b"\n"
            audit.write_bytes(b"".join(lines))
            rejected = self.run_tool(
                "project", "config", "verify-audit", "--state-dir", str(state)
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("audit record is malformed", rejected.stderr)

            audit.write_bytes(original.splitlines(keepends=True)[0])
            truncated = self.run_tool(
                "project", "config", "verify-audit", "--state-dir", str(state)
            )
            self.assertNotEqual(truncated.returncode, 0)
            self.assertIn("audit head differs", truncated.stderr)
            audit.write_bytes(original)
            restored = self.run_tool(
                "project", "config", "verify-audit", "--state-dir", str(state)
            )
            self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)

    def test_signed_audit_checkpoint_survives_growth_and_rejects_rollback(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.create_project(root, "CheckpointRobot")
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            first_plan, _ = self.plan(project, current, candidate)
            first = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(first_plan), "--current", str(current),
                "--candidate", str(candidate),
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

            state = project / "build/config-transactions"
            audit_path = state / "config-transaction-audit.jsonl"
            head_path = state / "config-transaction-audit.head.json"
            first_audit = audit_path.read_bytes()
            first_head = head_path.read_bytes()
            evidence = root / "external-audit-evidence"
            evidence.mkdir()
            private_path = evidence / "checkpoint-private.pem"
            public_path = evidence / "checkpoint-public.pem"
            checkpoint_path = evidence / "checkpoint.json"
            signature_path = evidence / "checkpoint.signature.json"
            report_path = evidence / "checkpoint.verification.json"
            key = Ed25519PrivateKey.generate()
            private_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
            public_path.write_bytes(key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
            public_sha = hashlib.sha256(public_path.read_bytes()).hexdigest()
            environment_name = "PDR_TEST_CONFIG_AUDIT_CHECKPOINT_KEY"
            with mock.patch.dict(os.environ, {environment_name: str(private_path)}):
                created = self.run_tool(
                    "project", "config", "audit-checkpoint",
                    "--state-dir", str(state), "--actor", "audit-anchor-service",
                    "--key-id", "audit-anchor-key-1",
                    "--private-key-path-environment", environment_name,
                    "--output", str(checkpoint_path),
                    "--signature-output", str(signature_path),
                )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["lastSequence"], 1)

            verifier = ROOT / "build/bin/pdr-signature-check.exe"
            verify_arguments = (
                "project", "config", "verify-audit-checkpoint",
                "--checkpoint", str(checkpoint_path),
                "--signature", str(signature_path),
                "--public-key", str(public_path),
                "--expected-key-id", "audit-anchor-key-1",
                "--expected-public-key-sha256", public_sha,
                "--signature-check-executable", str(verifier),
                "--state-dir", str(state), "--expected-min-sequence", "1",
                "--report", str(report_path),
            )
            verified = self.run_tool(*verify_arguments)
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            self.assertTrue(json.loads(report_path.read_text(
                encoding="utf-8"))["stateVerified"])

            site = project / "config/site/project.json"
            site.write_text(json.dumps({
                "version": 1,
                "values": {
                    "network": {"port": 9666},
                    "feature": {"enabled": False},
                },
            }), encoding="utf-8")
            candidate2 = project / "build/candidate-2.json"
            resolved = self.run_tool(
                "project", "config", "resolve", str(project / "pdr-project.yaml"),
                "--output", str(candidate2),
            )
            self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)
            second_plan, _ = self.plan(project, current, candidate2)
            second = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(second_plan), "--current", str(current),
                "--candidate", str(candidate2),
            )
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            grown = self.run_tool(*verify_arguments)
            self.assertEqual(grown.returncode, 0, grown.stdout + grown.stderr)
            self.assertEqual(json.loads(report_path.read_text(
                encoding="utf-8"))["currentSequence"], 2)

            checkpoint2_path = evidence / "checkpoint-2.json"
            signature2_path = evidence / "checkpoint-2.signature.json"
            report2_path = evidence / "checkpoint-2.verification.json"
            with mock.patch.dict(os.environ, {environment_name: str(private_path)}):
                created2 = self.run_tool(
                    "project", "config", "audit-checkpoint",
                    "--state-dir", str(state), "--actor", "audit-anchor-service",
                    "--key-id", "audit-anchor-key-1",
                    "--private-key-path-environment", environment_name,
                    "--output", str(checkpoint2_path),
                    "--signature-output", str(signature2_path),
                )
            self.assertEqual(created2.returncode, 0, created2.stdout + created2.stderr)
            self.assertEqual(json.loads(checkpoint2_path.read_text(
                encoding="utf-8"))["lastSequence"], 2)
            verify2_arguments = list(verify_arguments)
            verify2_arguments[verify2_arguments.index(str(checkpoint_path))] = str(
                checkpoint2_path)
            verify2_arguments[verify2_arguments.index(str(signature_path))] = str(
                signature2_path)
            verify2_arguments[verify2_arguments.index(str(report_path))] = str(report2_path)
            verify2_arguments[verify2_arguments.index("1")] = "2"
            verified2 = self.run_tool(*verify2_arguments)
            self.assertEqual(verified2.returncode, 0, verified2.stdout + verified2.stderr)

            audit_path.write_bytes(first_audit)
            head_path.write_bytes(first_head)
            first_journal = json.loads(first_audit)["journalFile"]
            for journal_path in state.glob("*.journal.json"):
                if journal_path.name != first_journal:
                    journal_path.unlink()
            rolled_back = self.run_tool(*verify2_arguments)
            self.assertNotEqual(rolled_back.returncode, 0)
            self.assertIn("audit chain is older than the checkpoint", rolled_back.stderr)

            tampered_path = evidence / "checkpoint.tampered.json"
            tampered = json.loads(checkpoint2_path.read_text(encoding="utf-8"))
            tampered["actor"] = "attacker"
            tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
            tampered_arguments = list(verify2_arguments)
            tampered_arguments[tampered_arguments.index(str(checkpoint2_path))] = str(
                tampered_path)
            rejected = self.run_tool(*tampered_arguments)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("checkpoint is malformed or corrupted", rejected.stderr)

    def test_recover_reconciles_audit_line_head_and_journal_pointer_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "AuditCrashRobot")
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            plan_path, _ = self.plan(project, current, candidate)
            applied = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate),
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            state = project / "build/config-transactions"
            journal_path = next(state.glob("*.journal.json"))
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            for field in ("auditSequence", "auditRecordSha256", "auditEvent"):
                journal.pop(field)
            transaction = load_transaction_tool()
            transaction.write_journal(journal_path, journal)
            (state / "config-transaction-audit.head.json").unlink()

            recovered = self.run_tool(
                "project", "config", "recover", str(project / "pdr-project.yaml"),
                "--journal", str(journal_path), "--actor", "recovery-operator",
            )
            self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
            repaired = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(repaired["auditSequence"], 1)
            verified = self.run_tool(
                "project", "config", "verify-audit", "--state-dir", str(state)
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            self.assertIn("records=1 journals=1", verified.stdout)

    def test_recovery_uses_private_plan_and_candidate_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "PrivateSnapshotRobot")
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            previous_bytes = current.read_bytes()
            plan_path, _ = self.plan(project, current, candidate)
            applied = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate),
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            state = project / "build/config-transactions"
            journal_path = next(state.glob("*.journal.json"))
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertNotEqual(journal["plan"], journal["planSource"])
            self.assertNotEqual(journal["candidateConfig"], journal["candidateSource"])
            journal["status"] = "activating"
            for field in (
                    "finishedAt", "activeConfigSha256", "auditSequence",
                    "auditRecordSha256", "auditEvent"):
                journal.pop(field, None)
            transaction = load_transaction_tool()
            transaction.write_journal(journal_path, journal)
            (state / "config-transaction-audit.jsonl").unlink()
            (state / "config-transaction-audit.head.json").unlink()

            plan_path.write_text(json.dumps({"replaced": True}), encoding="utf-8")
            candidate.write_text(json.dumps({"replaced": True}), encoding="utf-8")
            recovered = self.run_tool(
                "project", "config", "recover", str(project / "pdr-project.yaml"),
                "--journal", str(journal_path), "--actor", "recovery-operator",
            )
            self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
            self.assertEqual(current.read_bytes(), previous_bytes)
            verified = self.run_tool(
                "project", "config", "verify-audit", "--state-dir", str(state)
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_recovery_closes_an_interrupted_preparation_without_participants(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(Path(directory), "PreparationCrashRobot")
            self.configure_participants(project)
            current, candidate = self.resolve_pair(project)
            previous_bytes = current.read_bytes()
            plan_path, _ = self.plan(project, current, candidate)
            applied = self.run_tool(
                "project", "config", "apply", str(project / "pdr-project.yaml"),
                "--plan", str(plan_path), "--current", str(current),
                "--candidate", str(candidate),
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            state = project / "build/config-transactions"
            journal_path = next(state.glob("*.journal.json"))
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            journal["status"] = "preparing"
            journal["preflightCompleted"] = []
            journal["commitAttempted"] = []
            journal["commitCompleted"] = []
            journal["rollbackCompleted"] = []
            journal["events"] = []
            journal["errors"] = []
            for field in (
                    "finishedAt", "activeConfigSha256", "auditSequence",
                    "auditRecordSha256", "auditEvent"):
                journal.pop(field, None)
            transaction = load_transaction_tool()
            transaction.write_journal(journal_path, journal)
            current.write_bytes(previous_bytes)
            (state / "config-transaction-audit.jsonl").unlink()
            (state / "config-transaction-audit.head.json").unlink()
            for field in ("plan", "candidateConfig", "previousConfig"):
                (project / journal[field]).unlink(missing_ok=True)

            recovered = self.run_tool(
                "project", "config", "recover", str(project / "pdr-project.yaml"),
                "--journal", str(journal_path), "--actor", "recovery-operator",
            )
            self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
            closed = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(closed["status"], "rolled-back")
            self.assertIn("preparation was interrupted", closed["errors"][0])
            self.assertEqual(current.read_bytes(), previous_bytes)
            self.assertFalse((project / "build/agent.log").read_text(
                encoding="utf-8").endswith("rollback\n"))

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
            recovery_journal = {
                "schemaVersion": 2,
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
            }
            transaction.write_journal(journal, recovery_journal)
            journal_bytes = journal.read_bytes()
            tampered = json.loads(journal_bytes)
            tampered["commitAttempted"] = ["network-service"]
            journal.write_text(json.dumps(tampered), encoding="utf-8")
            rejected = self.run_tool(
                "project", "config", "recover", str(manifest), "--journal", str(journal)
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("journal hash mismatch", rejected.stderr)
            self.assertFalse((project / "build/agent.log").exists())
            journal.write_bytes(journal_bytes)
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
            repeated = self.run_tool(
                "project", "config", "recover", str(manifest), "--journal", str(journal)
            )
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
            self.assertIn("PDR_PROJECT_CONFIG_RECOVER_NOOP", repeated.stdout)
            self.assertEqual(
                (project / "build/agent.log").read_text(encoding="utf-8").splitlines(),
                ["feature-service:rollback", "network-service:rollback"],
            )


if __name__ == "__main__":
    unittest.main()
