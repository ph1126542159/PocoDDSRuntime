#!/usr/bin/env python3

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PDR = ROOT / "tools/pdr.py"
sys.path.insert(0, str(ROOT / "tools"))
import team_contract_registry_leader_backend as leader_backend_tool  # noqa: E402
import team_contract_registry_leader_backend_migration as migration_tool  # noqa: E402
EXAMPLE = ROOT / "examples/team-contract-registry-leader-backend-etcdctl"
ADAPTER = EXAMPLE / "etcd_backend_adapter.py"
CONFIG_TOOL = EXAMPLE / "create_backend_configs.py"
FAKE_ETCDCTL = ROOT / "tools/tests/fixtures/fake_etcdctl.py"


class LeaderEtcdAdapterTests(unittest.TestCase):
    @staticmethod
    def invoke(*command: str, environment: dict[str, str] | None = None) \
            -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command), check=False, capture_output=True, text=True,
            env=environment, timeout=30,
        )

    def test_pinned_mtls_etcd_transaction_adapter_passes_conformance(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            adapter = work / "etcd_backend_adapter.py"
            fake = work / "fake_etcdctl.py"
            shutil.copyfile(ADAPTER, adapter)
            shutil.copyfile(FAKE_ETCDCTL, fake)
            ca = work / "ca.pem"
            cert = work / "client.pem"
            key = work / "client-key.pem"
            ca.write_text("test-ca\n", encoding="utf-8")
            cert.write_text("test-client-cert\n", encoding="utf-8")
            key.write_text("test-client-key\n", encoding="utf-8")
            adapter_config = work / "etcd-adapter.json"
            backend_config = work / "backend.json"
            authority1 = "etcd-adapter-authority-0001"
            authority2 = "etcd-adapter-authority-0002"
            authority3 = "etcd-adapter-authority-0003"
            authority4 = "etcd-adapter-authority-0004"
            authority5 = "etcd-migration-transaction-0005"
            registry1 = "etcd-adapter-registry-0001"
            registry2 = "etcd-adapter-registry-0002"
            registry3 = "etcd-adapter-registry-0003"
            registry4 = "etcd-adapter-registry-0004"
            registry5 = "etcd-adapter-registry-0005"
            common = [
                sys.executable, str(CONFIG_TOOL),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(adapter.resolve()),
                "--adapter-id", "etcdctl-adapter-test",
                "--backend-id", "etcdctl-backend-test",
                "--authority-id", authority1,
                "--authority-id", authority2,
                "--authority-id", authority3,
                "--authority-id", authority4,
                "--authority-id", authority5,
                "--registry-id", registry1,
                "--registry-id", registry2,
                "--registry-id", registry3,
                "--registry-id", registry4,
                "--registry-id", registry5,
                "--etcdctl", str(Path(sys.executable).resolve()),
                "--etcdctl-argument", str(fake.resolve()),
                "--etcdctl-artifact", str(fake.resolve()),
                "--etcdctl-environment", "PDR_TEST_ETCDCTL_ROOT",
                "--etcdctl-environment", "PDR_TEST_ETCDCTL_MODE",
                "--endpoint", "https://etcd-1.example:2379",
                "--endpoint", "https://etcd-2.example:2379",
                "--endpoint", "https://etcd-3.example:2379",
                "--key-prefix", "/pdr/leader-authority/test-v1",
                "--cacert", str(ca.resolve()),
                "--cert", str(cert.resolve()),
                "--key", str(key.resolve()),
                "--adapter-config-output", str(adapter_config.resolve()),
                "--backend-config-output", str(backend_config.resolve()),
            ]
            generated = self.invoke(*common)
            self.assertEqual(
                generated.returncode, 0, generated.stdout + generated.stderr
            )
            self.assertIn("PDR_LEADER_ETCD_CONFIG_PASS", generated.stdout)
            adapter_document = json.loads(adapter_config.read_bytes())
            self.assertEqual(len(adapter_document["endpoints"]), 3)
            self.assertTrue(all(
                item.startswith("https://")
                for item in adapter_document["endpoints"]
            ))
            self.assertEqual(adapter_document["etcdctlVersion"], "3.6.0")
            backend_document = json.loads(backend_config.read_bytes())
            pinned_paths = {
                item["path"] for item in backend_document["artifactPins"]
            }
            self.assertTrue({
                str(adapter.resolve()), str(adapter_config.resolve()),
                str(fake.resolve()), str(ca.resolve()), str(cert.resolve()),
                str(key.resolve()),
            }.issubset(pinned_paths))

            store = work / "etcd-store"
            environment = dict(os.environ, **{
                "PDR_TEST_ETCDCTL_ROOT": str(store.resolve()),
                "PDR_TEST_ETCDCTL_MODE": "normal",
            })
            backend_sha = hashlib.sha256(backend_config.read_bytes()).hexdigest()
            adapter_sha = hashlib.sha256(adapter_config.read_bytes()).hexdigest()
            preflight_report = work / "preflight.json"
            preflight = self.invoke(
                sys.executable, str(PDR), "contract-package",
                "registry-leader-etcd-preflight",
                "--config", str(adapter_config.resolve()),
                "--expected-config-sha256", adapter_sha,
                "--report", str(preflight_report.resolve()),
                environment=environment,
            )
            self.assertEqual(
                preflight.returncode, 0, preflight.stdout + preflight.stderr
            )
            self.assertIn("endpoints=3 members=3", preflight.stdout)
            preflight_evidence = json.loads(preflight_report.read_bytes())
            self.assertTrue(preflight_evidence["passed"])
            self.assertEqual(len(preflight_evidence["memberIds"]), 3)
            mismatched_environment = dict(
                environment, PDR_TEST_ETCDCTL_MODE="cluster-mismatch"
            )
            mismatch = self.invoke(
                sys.executable, str(PDR), "contract-package",
                "registry-leader-etcd-preflight",
                "--config", str(adapter_config.resolve()),
                "--expected-config-sha256", adapter_sha,
                environment=mismatched_environment,
            )
            self.assertEqual(mismatch.returncode, 2)
            self.assertIn("disagree on cluster ID", mismatch.stderr)
            for mode, diagnostic_text in (
                ("health-failure", "etcdctl command failed"),
                ("leader-mismatch", "disagree on an elected member leader"),
                ("learner", "is a learner"),
                ("raft-lag", "Raft status is inconsistent"),
            ):
                fault = self.invoke(
                    sys.executable, str(PDR), "contract-package",
                    "registry-leader-etcd-preflight",
                    "--config", str(adapter_config.resolve()),
                    "--expected-config-sha256", adapter_sha,
                    environment=dict(environment, PDR_TEST_ETCDCTL_MODE=mode),
                )
                self.assertEqual(fault.returncode, 2, mode)
                self.assertIn(diagnostic_text, fault.stderr)
            initial_request = {
                "schemaVersion": 1,
                "product": "PocoDDSRuntimeTeamContractRegistryLeaderBackendRequest",
                "requestId": "etcd-adapter-initial-read",
                "backendId": "etcdctl-backend-test",
                "authorityId": authority1, "registryId": registry1,
                "operation": "read-current", "fencingToken": None,
                "grantSha256": None, "expectedCurrentToken": None,
                "expectedCurrentGrantSha256": None, "grantBase64": None,
            }
            initial = subprocess.run(
                [backend_document["executable"], *backend_document["arguments"]],
                input=json.dumps(initial_request).encode("utf-8"), check=False,
                capture_output=True, env=environment, timeout=10,
            )
            self.assertEqual(
                initial.returncode, 0,
                initial.stdout.decode(errors="replace")
                + initial.stderr.decode(errors="replace"),
            )
            self.assertFalse(json.loads(initial.stdout)["found"])
            diagnostic_grant = {
                "fencingToken": 1, "previousGrantSha256": None,
            }
            diagnostic_content = json.dumps(
                diagnostic_grant, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            diagnostic_request = dict(initial_request, **{
                "requestId": "etcd-adapter-initial-cas",
                "authorityId": authority3, "registryId": registry3,
                "operation": "compare-and-swap", "fencingToken": 1,
                "grantSha256": hashlib.sha256(diagnostic_content).hexdigest(),
                "expectedCurrentToken": 0,
                "expectedCurrentGrantSha256": "0" * 64,
                "grantBase64": base64.b64encode(diagnostic_content).decode("ascii"),
            })
            diagnostic = subprocess.run(
                [backend_document["executable"], *backend_document["arguments"]],
                input=json.dumps(diagnostic_request).encode("utf-8"), check=False,
                capture_output=True, env=environment, timeout=10,
            )
            self.assertEqual(
                diagnostic.returncode, 0,
                diagnostic.stdout.decode(errors="replace")
                + diagnostic.stderr.decode(errors="replace"),
            )
            self.assertTrue(json.loads(diagnostic.stdout)["committed"])
            acceptance_directory = work / "acceptance"
            accepted = self.invoke(
                sys.executable, str(PDR), "contract-package",
                "registry-leader-etcd-acceptance",
                "--adapter-config", str(adapter_config.resolve()),
                "--expected-adapter-config-sha256", adapter_sha,
                "--backend-config", str(backend_config.resolve()),
                "--expected-backend-config-sha256", backend_sha,
                "--authority-id", authority1,
                "--registry-id", registry1,
                "--confirm-dedicated-empty-scope",
                "--output-directory", str(acceptance_directory.resolve()),
                environment=environment,
            )
            self.assertEqual(
                accepted.returncode, 0, accepted.stdout + accepted.stderr
            )
            self.assertIn("PDR_REGISTRY_LEADER_ETCD_ACCEPTANCE_PASS", accepted.stdout)
            evidence = json.loads(
                (acceptance_directory / "acceptance.json").read_bytes()
            )
            self.assertTrue(evidence["passed"])
            self.assertEqual(evidence["backendProtocol"], {"major": 1, "minor": 0})
            self.assertRegex(
                evidence["capabilityManifestSha256"], r"^[0-9a-f]{64}$"
            )
            self.assertEqual(evidence["finalFencingToken"], 2)
            self.assertEqual(set(evidence["evidence"]), {
                "preflightBefore", "conformance", "preflightAfter"
            })
            for item in evidence["evidence"].values():
                stage_path = acceptance_directory / item["path"]
                self.assertEqual(
                    hashlib.sha256(stage_path.read_bytes()).hexdigest(),
                    item["sha256"],
                )
            rerun_directory = work / "acceptance-rerun"
            rerun = self.invoke(
                sys.executable, str(PDR), "contract-package",
                "registry-leader-etcd-acceptance",
                "--adapter-config", str(adapter_config.resolve()),
                "--expected-adapter-config-sha256", adapter_sha,
                "--backend-config", str(backend_config.resolve()),
                "--expected-backend-config-sha256", backend_sha,
                "--authority-id", authority1,
                "--registry-id", registry1,
                "--confirm-dedicated-empty-scope",
                "--output-directory", str(rerun_directory.resolve()),
                environment=environment,
            )
            self.assertEqual(rerun.returncode, 2)
            rerun_failure = json.loads(
                (rerun_directory / "acceptance-failure.json").read_bytes()
            )
            self.assertFalse(rerun_failure["passed"])
            self.assertFalse(rerun_failure["committed"])
            self.assertEqual(rerun_failure["stage"], "conformance")
            state = json.loads((store / "state.json").read_bytes())
            scope_fragment = (
                f"/authorities/{authority1}/registries/{registry1}/"
            )
            scope_keys = [item for item in state if scope_fragment in item]
            self.assertEqual(len(scope_keys), 3)
            self.assertEqual(sum(item.endswith("/current") for item in scope_keys), 1)
            self.assertEqual(sum("/grants/" in item for item in scope_keys), 2)

            checkpoint = work / "transaction-checkpoint.json"
            checkpoint.write_text("{}\n", encoding="utf-8")
            checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            os.environ["PDR_TEST_ETCDCTL_ROOT"] = str(store.resolve())
            os.environ["PDR_TEST_ETCDCTL_MODE"] = "normal"
            transaction_store = migration_tool.BackendTransactionStore(
                str(backend_config.resolve()), backend_sha,
                authority5, registry5,
            )
            transaction = {
                "schemaVersion": 2,
                "product": migration_tool.TRANSACTION_PRODUCT,
                "migrationId": authority5,
                "authorityId": "registry-leader-authority",
                "registryId": registry5,
                "sourceBackend": {
                    "kind": "external-command", "backendId": "source-store",
                    "configPath": str(backend_config.resolve()),
                    "configSha256": backend_sha,
                },
                "targetBackend": {
                    "kind": "external-command", "backendId": "target-store",
                    "configPath": str(backend_config.resolve()),
                    "configSha256": backend_sha,
                },
                "status": "active", "stateVersion": 1,
                "lastSyncEvidencePath": str(checkpoint.resolve()),
                "lastSyncEvidenceSha256": checkpoint_sha,
                "migrationEvidencePath": None,
                "migrationEvidenceSha256": None,
                "abortEvidencePath": None, "abortEvidenceSha256": None,
                "actor": "etcd.operator", "updatedAt":
                    "2026-08-26T12:00:00Z",
                "fencingToken": 1, "previousGrantSha256": None,
            }
            transaction_sha1 = transaction_store.compare_and_swap(
                leader_backend_tool.ZERO_SHA256, transaction,
                "begin", "etcd.operator",
            )
            loaded_transaction = transaction_store.read(transaction_sha1)
            self.assertIsNotNone(loaded_transaction)
            self.assertEqual(loaded_transaction[0], transaction)
            transaction2 = migration_tool._advance_transaction(
                transaction, "handoff.operator", transaction_sha1
            )
            transaction_sha2 = transaction_store.compare_and_swap(
                transaction_sha1, transaction2,
                "resume", "handoff.operator",
            )
            self.assertEqual(
                transaction_store.read(transaction_sha2)[0]["stateVersion"], 2
            )
            stale_transaction = migration_tool._advance_transaction(
                transaction, "stale.operator", transaction_sha1
            )
            with self.assertRaisesRegex(ValueError, "identity changed"):
                transaction_store.compare_and_swap(
                    transaction_sha1, stale_transaction,
                    "resume", "stale.operator",
                )
            transaction_state = json.loads((store / "state.json").read_bytes())
            transaction_scope = (
                f"/authorities/{authority5}/registries/{registry5}/"
            )
            transaction_keys = [
                item for item in transaction_state if transaction_scope in item
            ]
            self.assertEqual(len(transaction_keys), 3)
            self.assertEqual(
                sum("/grants/" in item for item in transaction_keys), 2
            )

            committed_failure_directory = work / "acceptance-committed-failure"
            committed_failure = self.invoke(
                sys.executable, str(PDR), "contract-package",
                "registry-leader-etcd-acceptance",
                "--adapter-config", str(adapter_config.resolve()),
                "--expected-adapter-config-sha256", adapter_sha,
                "--backend-config", str(backend_config.resolve()),
                "--expected-backend-config-sha256", backend_sha,
                "--authority-id", authority4,
                "--registry-id", registry4,
                "--confirm-dedicated-empty-scope",
                "--output-directory",
                str(committed_failure_directory.resolve()),
                environment=dict(
                    environment,
                    PDR_TEST_ETCDCTL_MODE="postflight-leader-mismatch",
                ),
            )
            self.assertEqual(committed_failure.returncode, 3)
            committed_failure_evidence = json.loads(
                (committed_failure_directory / "acceptance-failure.json")
                .read_bytes()
            )
            self.assertTrue(committed_failure_evidence["committed"])
            self.assertEqual(
                committed_failure_evidence["stage"], "preflight-after"
            )
            committed_scope_fragment = (
                f"/authorities/{authority4}/registries/{registry4}/"
            )
            committed_state = json.loads((store / "state.json").read_bytes())
            committed_scope_keys = [
                item for item in committed_state
                if committed_scope_fragment in item
            ]
            self.assertEqual(len(committed_scope_keys), 3)

            cert.write_text("tampered-client-cert\n", encoding="utf-8")
            rejected = self.invoke(
                sys.executable, str(PDR), "contract-package",
                "registry-leader-backend-conformance",
                "--backend-config", str(backend_config.resolve()),
                "--expected-backend-config-sha256", backend_sha,
                "--authority-id", authority2,
                "--registry-id", registry2,
                "--confirm-dedicated-empty-scope",
                environment=environment,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("artifact digest changed", rejected.stderr)
            state_after_rejection = json.loads((store / "state.json").read_bytes())
            self.assertFalse(any(
                f"/authorities/{authority2}/registries/{registry2}/" in item
                for item in state_after_rejection
            ))
            print(
                "PDR_REGISTRY_LEADER_ETCD_ADAPTER_PASS generated=1 https=1 "
                "mtls=1 version=1 preflight=1 quorum=1 split=1 health=1 "
                "leader=1 learner=1 lag=1 capability=1 acceptance=1 before=1 after=1 "
                "evidence=1 rerun=1 committed=1 namespace=1 txn=1 cas=1 concurrency=1 "
                "history=1 retained=1 pin=1"
                " migrationStore=1 stateCas=1 stateHistory=1 staleState=1"
            )

    def test_generator_rejects_insecure_or_single_endpoint_config(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for name in ("adapter.py", "fake.py", "ca", "cert", "key"):
                (work / name).write_text("fixture\n", encoding="utf-8")
            rejected = self.invoke(
                sys.executable, str(CONFIG_TOOL),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str((work / "adapter.py").resolve()),
                "--adapter-id", "insecure-adapter",
                "--backend-id", "insecure-backend",
                "--authority-id", "insecure-authority",
                "--registry-id", "insecure-registry",
                "--etcdctl", str(Path(sys.executable).resolve()),
                "--etcdctl-argument", str((work / "fake.py").resolve()),
                "--endpoint", "http://127.0.0.1:2379",
                "--key-prefix", "/pdr/insecure",
                "--cacert", str((work / "ca").resolve()),
                "--cert", str((work / "cert").resolve()),
                "--key", str((work / "key").resolve()),
                "--adapter-config-output", str((work / "adapter.json").resolve()),
                "--backend-config-output", str((work / "backend.json").resolve()),
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("malformed", rejected.stderr)
            self.assertFalse((work / "adapter.json").exists())


if __name__ == "__main__":
    unittest.main()
