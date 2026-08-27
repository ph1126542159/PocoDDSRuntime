#!/usr/bin/env python3
"""Portable and fail-closed Adapter Config Resolver tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from argparse import Namespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import team_contract_adapter_config_resolver as resolver_tool
import team_contract_adapter_catalog_fleet as fleet_tool


EXAMPLE = ROOT / "examples" / "team-contract-adapter-config-resolver-file"
GENERATOR = EXAMPLE / "create_resolver_config.py"
ADAPTER = EXAMPLE / "file_adapter_config_resolver_adapter.py"


CONFIG_TYPES = {
    "artifact-store": (
        "PocoDDSRuntimeTeamContractArtifactStoreConfig", "storeId",
        "portable-artifacts",
    ),
    "control-authorizer": (
        "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerConfig",
        "authorizerId", "portable-authorizer",
    ),
    "fleet-executor": (
        "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorConfig",
        "executorId", "portable-executor",
    ),
    "registry-leader-backend": (
        "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig", "backendId",
        "portable-state",
    ),
    "wave-gate": (
        "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateConfig", "gateId",
        "portable-gate",
    ),
}


class AdapterConfigResolverTest(unittest.TestCase):
    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def create_host(self, root: Path, host: str) -> tuple[Path, dict[str, Path]]:
        directory = root / host
        directory.mkdir()
        configs: dict[str, Path] = {}
        command = [
            sys.executable, str(GENERATOR), "--python",
            str(Path(sys.executable).resolve()), "--adapter",
            str(ADAPTER.resolve()), "--resolver-id", "fleet-config-resolver",
            "--scope", "adapter-catalog-fleet", "rollout-5", "catalog-main",
        ]
        for index, (kind, (product, identity_field, adapter_id)) in enumerate(
                sorted(CONFIG_TYPES.items()), start=1):
            path = directory / f"{kind}.json"
            path.write_text(json.dumps({
                "schemaVersion": 1, "product": product,
                identity_field: adapter_id, "hostMarker": host,
            }, sort_keys=True) + "\n", encoding="utf-8")
            configs[kind] = path
            command.extend([
                "--entry", f"fleet.{kind}", f"rev-{index}", kind,
                str(path.resolve()),
            ])
        mapping = directory / "mapping.json"
        config = directory / "resolver.json"
        command.extend([
            "--mapping-output", str(mapping.resolve()),
            "--output", str(config.resolve()),
        ])
        result = subprocess.run(
            command, check=False, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return config, configs

    @staticmethod
    def reference(kind: str) -> dict:
        ordered = sorted(CONFIG_TYPES)
        return {
            "kind": "adapter-config-ref",
            "resolverId": "fleet-config-resolver",
            "configId": f"fleet.{kind}", "adapterKind": kind,
            "adapterId": CONFIG_TYPES[kind][2],
            "revision": f"rev-{ordered.index(kind) + 1}",
        }

    def test_two_hosts_resolve_same_references_to_different_local_paths(self) \
            -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            config_a, configs_a = self.create_host(root, "host-a")
            config_b, configs_b = self.create_host(root, "host-b")
            resolver_a = resolver_tool.ExternalCommandAdapterConfigResolver(
                config_a, self.digest(config_a)
            )
            resolver_b = resolver_tool.ExternalCommandAdapterConfigResolver(
                config_b, self.digest(config_b)
            )
            self.assertEqual(resolver_a.resolver_id, resolver_b.resolver_id)
            self.assertNotEqual(
                resolver_a.config_sha256, resolver_b.config_sha256
            )
            for kind in sorted(CONFIG_TYPES):
                reference = self.reference(kind)
                document_a, path_a, _ = resolver_a.resolve(
                    reference, consumer_type="adapter-catalog-fleet",
                    consumer_id="rollout-5", resource_id="catalog-main",
                )
                document_b, path_b, _ = resolver_b.resolve(
                    reference, consumer_type="adapter-catalog-fleet",
                    consumer_id="rollout-5", resource_id="catalog-main",
                )
                self.assertEqual(path_a, configs_a[kind].resolve())
                self.assertEqual(path_b, configs_b[kind].resolve())
                self.assertNotEqual(path_a, path_b)
                self.assertEqual(document_a["hostMarker"], "host-a")
                self.assertEqual(document_b["hostMarker"], "host-b")
            self.assertRegex(
                resolver_a.capability_manifest_sha256, r"^[0-9a-f]{64}$"
            )
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({
                "product": "PocoDDSRuntimeTeamContractAdapterCatalog",
                "catalogId": "catalog-main", "generation": 2,
            }) + "\n", encoding="utf-8")
            plan_path = root / "plan-v5.json"
            command = [
                sys.executable,
                str(ROOT / "examples" / "team-contract-adapter-catalog" /
                    "create_fleet_plan.py"),
                "--rollout-id", "rollout-5", "--catalog", str(catalog),
                "--executor-config", str(configs_a["fleet-executor"]),
                "--gate-config", str(configs_a["wave-gate"]),
                "--control-authorizer-config",
                str(configs_a["control-authorizer"]),
                "--state-backend-config",
                str(configs_a["registry-leader-backend"]),
                "--artifact-store-config", str(configs_a["artifact-store"]),
                "--adapter-config-resolver-id", "fleet-config-resolver",
            ]
            for kind in sorted(CONFIG_TYPES):
                reference = self.reference(kind)
                command.extend([
                    "--config-ref", kind, reference["configId"],
                    reference["revision"],
                ])
            command.extend([
                "--wave", "canary", "canary", "0",
                "--node", "canary", "node-a", "rack-a", "1",
                "--wave-gate", "canary", "0", "1", "pause",
                "--output", str(plan_path),
            ])
            result = subprocess.run(
                command, check=False, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plan = json.loads(plan_path.read_bytes())
            fleet_tool.validate_plan(plan)
            self.assertEqual(plan["schemaVersion"], 5)
            self.assertFalse(any(
                key.endswith("ConfigPath") or key.endswith("ConfigSha256")
                for key in plan
            ))
            arguments = Namespace(
                adapter_config_resolver_config=str(config_a),
                expected_adapter_config_resolver_config_sha256=
                    self.digest(config_a),
                executor_config=None,
                expected_executor_config_sha256=None,
                state_backend_config=None, artifact_store_config=None,
            )

            def load_resolved(path, digest):
                resolved_path = Path(path).resolve()
                return (
                    json.loads(resolved_path.read_bytes()),
                    resolved_path, digest,
                )

            with (
                mock.patch.object(
                    fleet_tool, "load_executor_config",
                    side_effect=load_resolved,
                ),
                mock.patch.object(
                    fleet_tool.wave_gate_tool, "load_config",
                    side_effect=load_resolved,
                ),
                mock.patch.object(
                    fleet_tool.control_authorizer_tool, "load_config",
                    side_effect=load_resolved,
                ),
            ):
                bindings = fleet_tool.load_execution_bindings(plan, arguments)
            self.assertEqual(
                bindings["resolver"].resolver_id, "fleet-config-resolver"
            )
            self.assertEqual(bindings["executor"]["hostMarker"], "host-a")
            self.assertEqual(bindings["gate"]["hostMarker"], "host-a")
            self.assertEqual(bindings["authorizer"]["hostMarker"], "host-a")
            self.assertEqual(bindings["state"][0][0]["hostMarker"], "host-a")
            self.assertEqual(bindings["state"][1][0]["hostMarker"], "host-a")

    def test_scope_revision_kind_and_content_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            config, configs = self.create_host(root, "host-a")
            resolver = resolver_tool.ExternalCommandAdapterConfigResolver(
                config, self.digest(config)
            )
            reference = self.reference("fleet-executor")
            with self.assertRaisesRegex(RuntimeError, "scope"):
                resolver.resolve(
                    reference, consumer_type="adapter-catalog-fleet",
                    consumer_id="other-rollout", resource_id="catalog-main",
                )
            changed_revision = dict(reference, revision="rev-other")
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                resolver.resolve(
                    changed_revision, consumer_type="adapter-catalog-fleet",
                    consumer_id="rollout-5", resource_id="catalog-main",
                )
            wrong_kind = dict(
                reference, adapterKind="wave-gate",
                adapterId="portable-gate",
            )
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                resolver.resolve(
                    wrong_kind, consumer_type="adapter-catalog-fleet",
                    consumer_id="rollout-5", resource_id="catalog-main",
                )
            configs["fleet-executor"].write_bytes(
                configs["fleet-executor"].read_bytes() + b" \n"
            )
            with self.assertRaisesRegex(RuntimeError, "process failed"):
                resolver.resolve(
                    reference, consumer_type="adapter-catalog-fleet",
                    consumer_id="rollout-5", resource_id="catalog-main",
                )
        print(
            "PDR_ADAPTER_CONFIG_RESOLVER_PASS planV5=1 allConfigs=1 "
            "hostVariance=1 noHostPaths=1 protocol=1 portable=1 "
            "typed=1 identity=1 revision=1 scope=1 pins=1 drift=1 "
            "capability=1 redaction=1"
        )


if __name__ == "__main__":
    unittest.main()
