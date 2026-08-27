#!/usr/bin/env python3

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
PDR = TOOLS / "pdr.py"
GENERATOR = ROOT / "examples/team-contract-registry-leader-backend-file/create_backend_config.py"
ADAPTER = ROOT / "examples/team-contract-registry-leader-backend-file/file_backend_adapter.py"
ARTIFACT_GENERATOR = ROOT / (
    "examples/team-contract-artifact-store-file/create_artifact_store_config.py"
)
ARTIFACT_ADAPTER = ROOT / (
    "examples/team-contract-artifact-store-file/file_artifact_store_adapter.py"
)
RESOLVER_GENERATOR = ROOT / (
    "examples/team-contract-backend-config-resolver-file/create_resolver_config.py"
)
RESOLVER_ADAPTER = ROOT / (
    "examples/team-contract-backend-config-resolver-file/"
    "file_backend_config_resolver_adapter.py"
)
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_team_contract_registry as registry_test  # noqa: E402
import test_team_contract_registry_leader as leader_test  # noqa: E402


class LeaderBackendMigrationTests(unittest.TestCase):
    @staticmethod
    def invoke(*arguments: str,
               environment: dict[str, str] | None = None) \
            -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *arguments], check=False,
            capture_output=True, text=True, env=environment, timeout=30,
        )

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_fenced_bidirectional_backend_migration_preserves_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = registry_test.TeamContractRegistryTests()
            registry, package_policy, package_policy_sha, package_environment = \
                helper.initialized(root)
            package1 = helper.create_package(
                root, "1.0.0", "1.0.0", package_environment
            )
            self.assertEqual(
                helper.publish(
                    registry, package_policy, package_policy_sha, package1
                ).returncode,
                0,
            )
            package2 = helper.create_package(
                root, "1.0.1", "1.0.1", package_environment
            )
            package3 = helper.create_package(
                root, "1.0.2", "1.0.2", package_environment
            )
            leader_policy, leader_policy_sha, leader_environment = \
                leader_test.TeamContractRegistryLeaderTests.leader_fixture(root)
            environment = dict(leader_environment)
            source_store = root / "migration-source-store"
            target_store = root / "migration-target-store"
            environment.update({
                "PDR_MIGRATION_SOURCE_ROOT": str(source_store.resolve()),
                "PDR_MIGRATION_TARGET_ROOT": str(target_store.resolve()),
                "PDR_MIGRATION_TRANSACTION_ROOT": str(
                    (root / "migration-transaction-store").resolve()
                ),
                "PDR_MIGRATION_ARTIFACT_ROOT": str(
                    (root / "migration-artifact-store").resolve()
                ),
            })
            adapter = root / "file_backend_adapter.py"
            shutil.copyfile(ADAPTER, adapter)
            authority_id = "registry-leader-authority"
            registry_id = "unit-registry"
            node_id = "primary-oslo-01"

            def config(name: str, backend_id: str, root_environment: str) \
                    -> tuple[Path, str]:
                path = root / name
                result = self.invoke(
                    str(GENERATOR),
                    "--python", str(Path(sys.executable).resolve()),
                    "--adapter", str(adapter.resolve()),
                    "--backend-id", backend_id,
                    "--authority-id", authority_id,
                    "--registry-id", registry_id,
                    "--root-environment", root_environment,
                    "--output", str(path.resolve()),
                )
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                return path, self.digest(path)

            source_config, source_sha = config(
                "source.json", "migration-source", "PDR_MIGRATION_SOURCE_ROOT"
            )
            target_config, target_sha = config(
                "target.json", "migration-target", "PDR_MIGRATION_TARGET_ROOT"
            )
            transaction_config = root / "transaction-backend.json"
            transaction_config_result = self.invoke(
                str(GENERATOR),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(adapter.resolve()),
                "--backend-id", "migration-transaction-store",
                "--authority-id", "migration-distributed-probe",
                "--registry-id", registry_id,
                "--root-environment", "PDR_MIGRATION_TRANSACTION_ROOT",
                "--output", str(transaction_config.resolve()),
            )
            self.assertEqual(
                transaction_config_result.returncode, 0,
                transaction_config_result.stdout
                + transaction_config_result.stderr,
            )
            transaction_config_sha = self.digest(transaction_config)
            artifact_adapter = root / "file_artifact_store_adapter.py"
            shutil.copyfile(ARTIFACT_ADAPTER, artifact_adapter)
            artifact_config = root / "artifact-store.json"
            artifact_config_result = self.invoke(
                str(ARTIFACT_GENERATOR),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(artifact_adapter.resolve()),
                "--store-id", "migration-evidence-store",
                "--namespace-id", "migration-distributed-probe",
                "--namespace-id", "migration-forward",
                "--namespace-id", "migration-abort",
                "--namespace-id", "migration-rollback",
                "--root-environment", "PDR_MIGRATION_ARTIFACT_ROOT",
                "--output", str(artifact_config.resolve()),
            )
            self.assertEqual(
                artifact_config_result.returncode, 0,
                artifact_config_result.stdout + artifact_config_result.stderr,
            )
            artifact_config_sha = self.digest(artifact_config)
            resolver_adapter = root / "file_backend_config_resolver_adapter.py"
            shutil.copyfile(RESOLVER_ADAPTER, resolver_adapter)
            resolver_mapping = root / "backend-config-resolver-map.json"
            resolver_config = root / "backend-config-resolver.json"
            resolver_config_result = self.invoke(
                str(RESOLVER_GENERATOR),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(resolver_adapter.resolve()),
                "--resolver-id", "migration-backends",
                "--entry", "source", "deploy-2026-08",
                str(source_config.resolve()),
                "--entry", "target", "deploy-2026-08",
                str(target_config.resolve()),
                "--mapping-output", str(resolver_mapping.resolve()),
                "--output", str(resolver_config.resolve()),
            )
            self.assertEqual(
                resolver_config_result.returncode, 0,
                resolver_config_result.stdout + resolver_config_result.stderr,
            )
            resolver_config_sha = self.digest(resolver_config)

            def backend_ref(name: str, config_id: str,
                            backend_id: str) -> tuple[Path, str]:
                path = root / name
                path.write_text(json.dumps({
                    "kind": "backend-config-ref",
                    "resolverId": "migration-backends",
                    "configId": config_id, "backendId": backend_id,
                    "revision": "deploy-2026-08",
                }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                return path, self.digest(path)

            source_ref, source_ref_sha = backend_ref(
                "source-ref.json", "source", "migration-source"
            )
            target_ref, target_ref_sha = backend_ref(
                "target-ref.json", "target", "migration-target"
            )
            now = datetime.now(timezone.utc)
            issued = (now - timedelta(minutes=2)).isoformat()
            not_before = (now - timedelta(minutes=1)).isoformat()
            expires = (now + timedelta(hours=1)).isoformat()
            leader_trust = [
                "--leader-trust-policy", str(leader_policy),
                "--expected-leader-trust-policy-id",
                "registry-leader-authorities",
                "--expected-leader-trust-policy-sha256", leader_policy_sha,
            ]
            package_trust = [
                "--trust-policy", str(package_policy),
                "--expected-trust-policy-id", "registry-unit-policy",
                "--expected-trust-policy-sha256", package_policy_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
            ]

            def pointer() -> dict:
                return json.loads((registry / "registry.json").read_bytes())

            def issue(config_path: Path, config_sha: str, purpose: str,
                      expected_token: int, previous_sha: str) -> str:
                current = pointer()
                command = [
                    str(PDR), "contract-package", "registry-leader-issue",
                    "--authority-backend-config", str(config_path.resolve()),
                    "--expected-authority-backend-config-sha256", config_sha,
                    "--authority-id", authority_id,
                    "--registry-id", registry_id,
                    "--purpose", purpose,
                    "--expected-current-token", str(expected_token),
                    "--expected-current-grant-sha256", previous_sha,
                    "--baseline-revision", str(current["revision"]),
                    "--baseline-state-sha256", current["stateSha256"],
                    "--issued-at", issued, "--not-before", not_before,
                    "--expires-at", expires,
                    "--key-id", "oslo-leader-authority-2026",
                    "--private-key-environment", "PDR_TEST_LEADER_KEY",
                    "--operator", "ha.operator", *leader_trust,
                ]
                if purpose == "leadership":
                    command.extend(["--leader-id", node_id])
                result = self.invoke(*command, environment=environment)
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                return result.stdout.strip().rsplit("sha256=", 1)[1]

            def activate(config_path: Path, config_sha: str, grant_sha: str,
                         migration: Path | None = None) \
                    -> subprocess.CompletedProcess[str]:
                command = [
                    str(PDR), "contract-package", "registry-leader-activate",
                    "--registry", str(registry), "--node-id", node_id,
                    "--authority-backend-config", str(config_path.resolve()),
                    "--expected-authority-backend-config-sha256", config_sha,
                    "--authority-id", authority_id,
                    "--expected-current-grant-sha256", grant_sha,
                    "--operator", "ha.operator", "--operation-audit",
                    str(root / "leader-audit.jsonl"),
                    "--leader-verification-time", now.isoformat(),
                    *package_trust, *leader_trust,
                ]
                if migration is None:
                    command.append("--confirm-enroll-primary")
                else:
                    command.extend([
                        "--backend-migration-evidence", str(migration.resolve()),
                        "--expected-backend-migration-evidence-sha256",
                        self.digest(migration),
                        "--artifact-store-config",
                        str(artifact_config.resolve()),
                        "--expected-artifact-store-config-sha256",
                        artifact_config_sha,
                        "--backend-config-resolver-config",
                        str(resolver_config.resolve()),
                        "--expected-backend-config-resolver-config-sha256",
                        resolver_config_sha,
                    ])
                return self.invoke(*command, environment=environment)

            def sync(migration_id: str, source: Path, source_digest: str,
                     target: Path, target_digest: str, output: Path,
                     transaction: Path | None = None,
                     portable: bool = False) -> dict:
                command = [
                    str(PDR), "contract-package",
                    "registry-leader-backend-migration-sync",
                    "--migration-id", migration_id,
                    "--authority-id", authority_id,
                    "--registry-id", registry_id,
                    "--confirm-target-migration-scope",
                    "--output", str(output.resolve()),
                ]
                if portable:
                    source_reference = source_ref \
                        if source == source_config else target_ref
                    source_reference_sha = source_ref_sha \
                        if source == source_config else target_ref_sha
                    target_reference = source_ref \
                        if target == source_config else target_ref
                    target_reference_sha = source_ref_sha \
                        if target == source_config else target_ref_sha
                    command.extend([
                        "--source-backend-ref", str(source_reference.resolve()),
                        "--expected-source-backend-ref-sha256",
                        source_reference_sha,
                        "--target-backend-ref", str(target_reference.resolve()),
                        "--expected-target-backend-ref-sha256",
                        target_reference_sha,
                        "--backend-config-resolver-config",
                        str(resolver_config.resolve()),
                        "--expected-backend-config-resolver-config-sha256",
                        resolver_config_sha,
                    ])
                else:
                    command.extend([
                        "--source-backend-config", str(source.resolve()),
                        "--expected-source-backend-config-sha256", source_digest,
                        "--target-backend-config", str(target.resolve()),
                        "--expected-target-backend-config-sha256", target_digest,
                    ])
                if transaction is not None:
                    command.extend([
                        "--transaction", str(transaction.resolve()),
                        "--artifact-store-config", str(artifact_config.resolve()),
                        "--expected-artifact-store-config-sha256",
                        artifact_config_sha,
                        "--actor", "ha.operator",
                    ])
                result = self.invoke(*command, environment=environment)
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                return json.loads(output.read_bytes())

            def finalize(migration_id: str, sync_path: Path,
                         target_grant_sha: str, output: Path,
                         transaction: Path | None = None) -> dict:
                command = [
                    str(PDR), "contract-package",
                    "registry-leader-backend-migration-finalize",
                    "--migration-id", migration_id,
                    "--registry", str(registry),
                    "--authority-id", authority_id,
                    "--registry-id", registry_id,
                    "--sync-evidence", str(sync_path.resolve()),
                    "--expected-sync-evidence-sha256", self.digest(sync_path),
                    "--expected-target-grant-sha256", target_grant_sha,
                    "--leader-verification-time", now.isoformat(),
                    *package_trust,
                    "--backend-config-resolver-config",
                    str(resolver_config.resolve()),
                    "--expected-backend-config-resolver-config-sha256",
                    resolver_config_sha,
                    "--output", str(output.resolve()),
                ]
                if transaction is not None:
                    command.extend([
                        "--transaction", str(transaction.resolve()),
                        "--artifact-store-config", str(artifact_config.resolve()),
                        "--expected-artifact-store-config-sha256",
                        artifact_config_sha,
                        "--expected-transaction-sha256",
                        self.digest(transaction),
                        "--actor", "ha.operator",
                    ])
                result = self.invoke(*command, environment=environment)
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                return json.loads(output.read_bytes())

            def status(transaction: Path, report: Path) -> dict:
                result = self.invoke(
                    str(PDR), "contract-package",
                    "registry-leader-backend-migration-status",
                    "--transaction", str(transaction.resolve()),
                    "--artifact-store-config", str(artifact_config.resolve()),
                    "--expected-artifact-store-config-sha256",
                    artifact_config_sha,
                    "--backend-config-resolver-config",
                    str(resolver_config.resolve()),
                    "--expected-backend-config-resolver-config-sha256",
                    resolver_config_sha,
                    "--registry", str(registry),
                    "--report", str(report.resolve()),
                    environment=environment,
                )
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                return json.loads(report.read_bytes())

            def resume(transaction: Path, expected_sha: str,
                       output: Path) -> subprocess.CompletedProcess[str]:
                return self.invoke(
                    str(PDR), "contract-package",
                    "registry-leader-backend-migration-resume",
                    "--transaction", str(transaction.resolve()),
                    "--artifact-store-config", str(artifact_config.resolve()),
                    "--expected-artifact-store-config-sha256",
                    artifact_config_sha,
                    "--backend-config-resolver-config",
                    str(resolver_config.resolve()),
                    "--expected-backend-config-resolver-config-sha256",
                    resolver_config_sha,
                    "--expected-transaction-sha256", expected_sha,
                    "--actor", "ha.operator",
                    "--confirm-target-migration-scope",
                    "--output", str(output.resolve()),
                    environment=environment,
                )

            def reconcile_sync(transaction: Path, sync_path: Path,
                               expected_transaction_sha: str | None = None) \
                    -> subprocess.CompletedProcess[str]:
                command = [
                    str(PDR), "contract-package",
                    "registry-leader-backend-migration-reconcile",
                    "--transaction", str(transaction.resolve()),
                    "--artifact-store-config", str(artifact_config.resolve()),
                    "--expected-artifact-store-config-sha256",
                    artifact_config_sha,
                    "--backend-config-resolver-config",
                    str(resolver_config.resolve()),
                    "--expected-backend-config-resolver-config-sha256",
                    resolver_config_sha,
                    "--actor", "ha.operator",
                    "--sync-evidence", str(sync_path.resolve()),
                    "--expected-sync-evidence-sha256", self.digest(sync_path),
                ]
                if expected_transaction_sha is None:
                    command.append("--confirm-adopt-orphaned-sync")
                else:
                    command.extend([
                        "--expected-transaction-sha256",
                        expected_transaction_sha,
                    ])
                return self.invoke(*command, environment=environment)

            def reconcile_complete(transaction: Path,
                                   migration_path: Path) \
                    -> subprocess.CompletedProcess[str]:
                return self.invoke(
                    str(PDR), "contract-package",
                    "registry-leader-backend-migration-reconcile",
                    "--transaction", str(transaction.resolve()),
                    "--artifact-store-config", str(artifact_config.resolve()),
                    "--expected-artifact-store-config-sha256",
                    artifact_config_sha,
                    "--backend-config-resolver-config",
                    str(resolver_config.resolve()),
                    "--expected-backend-config-resolver-config-sha256",
                    resolver_config_sha,
                    "--expected-transaction-sha256",
                    self.digest(transaction),
                    "--actor", "ha.operator",
                    "--migration-evidence", str(migration_path.resolve()),
                    "--expected-migration-evidence-sha256",
                    self.digest(migration_path),
                    "--registry", str(registry),
                    environment=environment,
                )

            def abort(transaction: Path, output: Path) \
                    -> subprocess.CompletedProcess[str]:
                return self.invoke(
                    str(PDR), "contract-package",
                    "registry-leader-backend-migration-abort",
                    "--transaction", str(transaction.resolve()),
                    "--artifact-store-config", str(artifact_config.resolve()),
                    "--expected-artifact-store-config-sha256",
                    artifact_config_sha,
                    "--backend-config-resolver-config",
                    str(resolver_config.resolve()),
                    "--expected-backend-config-resolver-config-sha256",
                    resolver_config_sha,
                    "--expected-transaction-sha256",
                    self.digest(transaction),
                    "--registry", str(registry),
                    "--operator", "ha.operator",
                    "--reason", "operator cancelled before fence",
                    "--output", str(output.resolve()),
                    environment=environment,
                )

            grant1_sha = issue(
                source_config, source_sha, "leadership", 0, "0" * 64
            )
            enrolled = activate(source_config, source_sha, grant1_sha)
            self.assertEqual(
                enrolled.returncode, 0, enrolled.stdout + enrolled.stderr
            )

            distributed_sync_path = root / "distributed-sync.json"
            distributed_sync = self.invoke(
                str(PDR), "contract-package",
                "registry-leader-backend-migration-sync",
                "--migration-id", "migration-distributed-probe",
                "--authority-id", authority_id,
                "--registry-id", registry_id,
                "--source-backend-ref", str(source_ref.resolve()),
                "--expected-source-backend-ref-sha256", source_ref_sha,
                "--target-backend-ref", str(target_ref.resolve()),
                "--expected-target-backend-ref-sha256", target_ref_sha,
                "--backend-config-resolver-config",
                str(resolver_config.resolve()),
                "--expected-backend-config-resolver-config-sha256",
                resolver_config_sha,
                "--confirm-target-migration-scope",
                "--transaction-backend-config",
                str(transaction_config.resolve()),
                "--expected-transaction-backend-config-sha256",
                transaction_config_sha,
                "--artifact-store-config", str(artifact_config.resolve()),
                "--expected-artifact-store-config-sha256",
                artifact_config_sha,
                "--actor", "distributed.operator",
                "--output", str(distributed_sync_path.resolve()),
                environment=environment,
            )
            self.assertEqual(
                distributed_sync.returncode, 0,
                distributed_sync.stdout + distributed_sync.stderr,
            )
            distributed_sync_path.unlink()
            distributed_status_path = root / "distributed-status.json"
            distributed_status = self.invoke(
                str(PDR), "contract-package",
                "registry-leader-backend-migration-status",
                "--transaction-backend-config",
                str(transaction_config.resolve()),
                "--expected-transaction-backend-config-sha256",
                transaction_config_sha,
                "--artifact-store-config", str(artifact_config.resolve()),
                "--expected-artifact-store-config-sha256",
                artifact_config_sha,
                "--backend-config-resolver-config",
                str(resolver_config.resolve()),
                "--expected-backend-config-resolver-config-sha256",
                resolver_config_sha,
                "--migration-id", "migration-distributed-probe",
                "--registry-id", registry_id,
                "--registry", str(registry),
                "--report", str(distributed_status_path.resolve()),
                environment=environment,
            )
            self.assertEqual(
                distributed_status.returncode, 0,
                distributed_status.stdout + distributed_status.stderr,
            )
            distributed_report = json.loads(
                distributed_status_path.read_bytes()
            )
            self.assertEqual(
                distributed_report["transactionStore"]["kind"],
                "external-command",
            )
            self.assertEqual(distributed_report["schemaVersion"], 4)
            self.assertEqual(
                distributed_report["backendConfigResolver"]["resolverId"],
                "migration-backends",
            )
            transaction_current = json.loads((
                root / "migration-transaction-store"
                / "migration-distributed-probe" / registry_id / "current.json"
            ).read_bytes())
            self.assertEqual(transaction_current["schemaVersion"], 4)
            self.assertNotIn("lastSyncEvidencePath", transaction_current)
            self.assertNotIn(
                "configPath", transaction_current["sourceBackend"]
            )
            self.assertEqual(
                transaction_current["backendConfigResolverId"],
                "migration-backends",
            )
            self.assertEqual(
                transaction_current["lastSyncEvidenceRef"]["storeId"],
                "migration-evidence-store",
            )
            distributed_resume_path = root / "distributed-resume.json"
            distributed_resume = self.invoke(
                str(PDR), "contract-package",
                "registry-leader-backend-migration-resume",
                "--transaction-backend-config",
                str(transaction_config.resolve()),
                "--expected-transaction-backend-config-sha256",
                transaction_config_sha,
                "--artifact-store-config", str(artifact_config.resolve()),
                "--expected-artifact-store-config-sha256",
                artifact_config_sha,
                "--backend-config-resolver-config",
                str(resolver_config.resolve()),
                "--expected-backend-config-resolver-config-sha256",
                resolver_config_sha,
                "--migration-id", "migration-distributed-probe",
                "--registry-id", registry_id,
                "--expected-transaction-sha256",
                distributed_report["transactionSha256"],
                "--actor", "handoff.operator",
                "--confirm-target-migration-scope",
                "--output", str(distributed_resume_path.resolve()),
                environment=environment,
            )
            self.assertEqual(
                distributed_resume.returncode, 0,
                distributed_resume.stdout + distributed_resume.stderr,
            )
            distributed_resume_path.unlink()
            distributed_status2_path = root / "distributed-status2.json"
            distributed_status2 = self.invoke(
                str(PDR), "contract-package",
                "registry-leader-backend-migration-status",
                "--transaction-backend-config",
                str(transaction_config.resolve()),
                "--expected-transaction-backend-config-sha256",
                transaction_config_sha,
                "--artifact-store-config", str(artifact_config.resolve()),
                "--expected-artifact-store-config-sha256",
                artifact_config_sha,
                "--backend-config-resolver-config",
                str(resolver_config.resolve()),
                "--expected-backend-config-resolver-config-sha256",
                resolver_config_sha,
                "--migration-id", "migration-distributed-probe",
                "--registry-id", registry_id,
                "--registry", str(registry),
                "--report", str(distributed_status2_path.resolve()),
                environment=environment,
            )
            self.assertEqual(distributed_status2.returncode, 0)
            distributed_report2 = json.loads(
                distributed_status2_path.read_bytes()
            )
            distributed_abort = self.invoke(
                str(PDR), "contract-package",
                "registry-leader-backend-migration-abort",
                "--transaction-backend-config",
                str(transaction_config.resolve()),
                "--expected-transaction-backend-config-sha256",
                transaction_config_sha,
                "--artifact-store-config", str(artifact_config.resolve()),
                "--expected-artifact-store-config-sha256",
                artifact_config_sha,
                "--backend-config-resolver-config",
                str(resolver_config.resolve()),
                "--expected-backend-config-resolver-config-sha256",
                resolver_config_sha,
                "--migration-id", "migration-distributed-probe",
                "--registry-id", registry_id,
                "--expected-transaction-sha256",
                distributed_report2["transactionSha256"],
                "--registry", str(registry),
                "--operator", "handoff.operator",
                "--reason", "distributed transaction probe complete",
                "--output", str((root / "distributed-abort.json").resolve()),
                environment=environment,
            )
            self.assertEqual(
                distributed_abort.returncode, 0,
                distributed_abort.stdout + distributed_abort.stderr,
            )
            transaction_final = json.loads((
                root / "migration-transaction-store"
                / "migration-distributed-probe" / registry_id / "current.json"
            ).read_bytes())
            self.assertEqual(transaction_final["status"], "aborted")
            self.assertEqual(transaction_final["stateVersion"], 3)
            self.assertEqual(
                transaction_final["abortEvidenceRef"]["storeId"],
                "migration-evidence-store",
            )
            artifact_files = list((
                root / "migration-artifact-store" / "migration-evidence-store"
                / "migration-distributed-probe"
            ).rglob("*.artifact"))
            self.assertEqual(len(artifact_files), 3)

            forward_transaction = root / "migration-forward.transaction.json"
            online_sync = sync(
                "migration-forward", source_config, source_sha,
                target_config, target_sha, root / "online-sync.json",
                forward_transaction, portable=True,
            )
            self.assertEqual(online_sync["synchronizedThroughToken"], 1)
            online_status = status(
                forward_transaction, root / "online-status.json"
            )
            self.assertEqual(online_status["phase"], "synchronized")
            self.assertTrue(online_status["safeToAbort"])
            self.assertEqual(online_status["schemaVersion"], 4)
            self.assertEqual(
                online_status["artifactStore"]["storeId"],
                "migration-evidence-store",
            )
            self.assertEqual(
                online_status["lastSyncEvidenceRef"]["namespaceId"],
                "migration-forward",
            )

            fence2_sha = issue(source_config, source_sha, "fence", 1, grant1_sha)
            fence_sync_path = root / "fence-sync.json"
            pre_resume_sha = self.digest(forward_transaction)
            resumed = resume(
                forward_transaction, pre_resume_sha, fence_sync_path
            )
            self.assertEqual(
                resumed.returncode, 0, resumed.stdout + resumed.stderr
            )
            fence_sync = json.loads(fence_sync_path.read_bytes())
            self.assertEqual(fence_sync["synchronizedThroughToken"], 2)
            stale_resume = resume(
                forward_transaction, pre_resume_sha, root / "stale-sync.json"
            )
            self.assertEqual(stale_resume.returncode, 2)
            self.assertIn("transaction identity changed", stale_resume.stderr)
            fenced_status = status(
                forward_transaction, root / "fenced-status.json"
            )
            self.assertEqual(fenced_status["phase"], "source-fenced")
            self.assertFalse(fenced_status["safeToAbort"])
            forbidden_abort = abort(
                forward_transaction, root / "forbidden-abort.json"
            )
            self.assertEqual(forbidden_abort.returncode, 2)
            self.assertIn("cannot abort after fencing", forbidden_abort.stderr)
            grant3_sha = issue(
                target_config, target_sha, "leadership", 2, fence2_sha
            )
            migration_path = root / "migration-forward.json"
            migration = finalize(
                "migration-forward", fence_sync_path, grant3_sha,
                migration_path, forward_transaction,
            )
            self.assertEqual(migration["sourceFenceToken"], 2)
            self.assertEqual(migration["targetLeadershipToken"], 3)
            self.assertEqual(migration["schemaVersion"], 2)
            self.assertNotIn("syncEvidencePath", migration)

            tampered_migration_path = root / "migration-forward-tampered.json"
            tampered_migration = dict(migration)
            tampered_migration["targetLeadershipGrantSha256"] = "f" * 64
            tampered_migration_path.write_text(
                json.dumps(tampered_migration, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            tampered = activate(
                target_config, target_sha, grant3_sha,
                tampered_migration_path,
            )
            self.assertEqual(tampered.returncode, 2)
            self.assertIn("does not bind activation", tampered.stderr)

            no_evidence = activate(target_config, target_sha, grant3_sha)
            self.assertEqual(no_evidence.returncode, 2)
            self.assertIn("cannot change the authority backend", no_evidence.stderr)
            migrated = activate(
                target_config, target_sha, grant3_sha, migration_path
            )
            self.assertEqual(
                migrated.returncode, 0, migrated.stdout + migrated.stderr
            )
            self.assertIn("operation=migrate", migrated.stdout)
            binding = json.loads((registry / ".pdr-leader.json").read_bytes())
            self.assertEqual(binding["schemaVersion"], 3)
            self.assertEqual(
                binding["authorityBackend"]["backendId"], "migration-target"
            )
            self.assertEqual(
                binding["backendMigrationEvidenceSha256"],
                self.digest(migration_path),
            )
            cutover_status = status(
                forward_transaction, root / "cutover-status.json"
            )
            self.assertEqual(cutover_status["phase"], "cutover-complete")
            self.assertEqual(cutover_status["transactionStatus"], "prepared")
            completed = reconcile_complete(
                forward_transaction, migration_path
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            completed_status = status(
                forward_transaction, root / "completed-status.json"
            )
            self.assertEqual(completed_status["transactionStatus"], "completed")
            completed_resume = resume(
                forward_transaction, self.digest(forward_transaction),
                root / "completed-resume.json",
            )
            self.assertEqual(completed_resume.returncode, 2)
            self.assertIn("only an active", completed_resume.stderr)

            published2 = self.invoke(
                str(PDR), "contract-package", "registry-publish",
                *helper.common(registry, package_policy, package_policy_sha),
                "--package", str(package2), "--actor", "publisher",
                "--occurred-at", "2026-08-25T12:20:00Z",
                environment=environment,
            )
            self.assertEqual(
                published2.returncode, 0, published2.stdout + published2.stderr
            )

            abort_transaction = root / "migration-abort.transaction.json"
            abort_sync = root / "abort-online-sync.json"
            sync(
                "migration-abort", target_config, target_sha,
                source_config, source_sha, abort_sync, abort_transaction,
            )
            abort_status = status(
                abort_transaction, root / "abort-ready-status.json"
            )
            self.assertTrue(abort_status["safeToAbort"])
            aborted = abort(abort_transaction, root / "abort.json")
            self.assertEqual(
                aborted.returncode, 0, aborted.stdout + aborted.stderr
            )
            after_abort = status(
                abort_transaction, root / "aborted-status.json"
            )
            self.assertEqual(after_abort["phase"], "aborted")
            blocked_resume = resume(
                abort_transaction, self.digest(abort_transaction),
                root / "aborted-resume.json",
            )
            self.assertEqual(blocked_resume.returncode, 2)
            self.assertIn("only an active", blocked_resume.stderr)

            rollback_online = root / "rollback-online-sync.json"
            sync(
                "migration-rollback", target_config, target_sha,
                source_config, source_sha, rollback_online,
            )
            rollback_transaction = root / "migration-rollback.transaction.json"
            adopted = reconcile_sync(
                rollback_transaction, rollback_online
            )
            self.assertEqual(
                adopted.returncode, 0, adopted.stdout + adopted.stderr
            )
            fence4_sha = issue(target_config, target_sha, "fence", 3, grant3_sha)
            rollback_fence_sync = root / "rollback-fence-sync.json"
            rollback_resumed = resume(
                rollback_transaction, self.digest(rollback_transaction),
                rollback_fence_sync,
            )
            self.assertEqual(
                rollback_resumed.returncode, 0,
                rollback_resumed.stdout + rollback_resumed.stderr,
            )
            rollback_sync = json.loads(rollback_fence_sync.read_bytes())
            self.assertEqual(rollback_sync["synchronizedThroughToken"], 4)
            grant5_sha = issue(
                source_config, source_sha, "leadership", 4, fence4_sha
            )
            rollback_migration_path = root / "migration-rollback.json"
            rollback = finalize(
                "migration-rollback", rollback_fence_sync,
                grant5_sha, rollback_migration_path, rollback_transaction,
            )
            self.assertEqual(rollback["targetLeadershipToken"], 5)
            rolled_back = activate(
                source_config, source_sha, grant5_sha,
                rollback_migration_path,
            )
            self.assertEqual(
                rolled_back.returncode, 0,
                rolled_back.stdout + rolled_back.stderr,
            )
            self.assertIn("operation=migrate", rolled_back.stdout)
            rollback_binding = json.loads(
                (registry / ".pdr-leader.json").read_bytes()
            )
            self.assertEqual(
                rollback_binding["authorityBackend"]["backendId"],
                "migration-source",
            )
            rollback_completed = reconcile_complete(
                rollback_transaction, rollback_migration_path
            )
            self.assertEqual(
                rollback_completed.returncode, 0,
                rollback_completed.stdout + rollback_completed.stderr,
            )
            published3 = self.invoke(
                str(PDR), "contract-package", "registry-publish",
                *helper.common(registry, package_policy, package_policy_sha),
                "--package", str(package3), "--actor", "publisher",
                "--occurred-at", "2026-08-25T12:30:00Z",
                environment=environment,
            )
            self.assertEqual(
                published3.returncode, 0, published3.stdout + published3.stderr
            )
            print(
                "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_PASS "
                "online=1 chain=1 fence=1 evidence=1 cutover=1 binding=1 "
                "write=1 rollback=1 rollbackWrite=1 noEvidence=1 tamper=1 "
                "status=1 resume=1 stale=1 reconcile=1 abort=1 "
                "postFenceAbort=1 terminal=1 store=1 distributedCas=1 "
                "artifactStore=1 portableRef=1 noSharedPath=1 artifactHistory=1 "
                "configResolver=1 pathlessConfig=1 transactionV4=1"
            )


if __name__ == "__main__":
    unittest.main()
