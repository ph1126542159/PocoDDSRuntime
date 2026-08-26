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
            registry1 = "etcd-adapter-registry-0001"
            registry2 = "etcd-adapter-registry-0002"
            registry3 = "etcd-adapter-registry-0003"
            common = [
                sys.executable, str(CONFIG_TOOL),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(adapter.resolve()),
                "--adapter-id", "etcdctl-adapter-test",
                "--backend-id", "etcdctl-backend-test",
                "--authority-id", authority1,
                "--authority-id", authority2,
                "--authority-id", authority3,
                "--registry-id", registry1,
                "--registry-id", registry2,
                "--registry-id", registry3,
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
            report = work / "conformance.json"
            qualified = self.invoke(
                sys.executable, str(PDR), "contract-package",
                "registry-leader-backend-conformance",
                "--backend-config", str(backend_config.resolve()),
                "--expected-backend-config-sha256", backend_sha,
                "--authority-id", authority1,
                "--registry-id", registry1,
                "--confirm-dedicated-empty-scope",
                "--report", str(report.resolve()),
                environment=environment,
            )
            self.assertEqual(
                qualified.returncode, 0, qualified.stdout + qualified.stderr
            )
            self.assertIn("checks=6 token=2", qualified.stdout)
            evidence = json.loads(report.read_bytes())
            self.assertEqual(evidence["finalFencingToken"], 2)
            state = json.loads((store / "state.json").read_bytes())
            scope_fragment = (
                f"/authorities/{authority1}/registries/{registry1}/"
            )
            scope_keys = [item for item in state if scope_fragment in item]
            self.assertEqual(len(scope_keys), 3)
            self.assertEqual(sum(item.endswith("/current") for item in scope_keys), 1)
            self.assertEqual(sum("/grants/" in item for item in scope_keys), 2)

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
                "mtls=1 version=1 preflight=1 quorum=1 split=1 namespace=1 "
                "txn=1 cas=1 concurrency=1 history=1 retained=1 pin=1"
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
