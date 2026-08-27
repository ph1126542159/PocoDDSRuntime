#!/usr/bin/env python3

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
PDR = TOOLS / "pdr.py"
BACKEND_GENERATOR = ROOT / (
    "examples/team-contract-registry-leader-backend-file/create_backend_config.py"
)
BACKEND_ADAPTER = ROOT / (
    "examples/team-contract-registry-leader-backend-file/file_backend_adapter.py"
)
RESOLVER_GENERATOR = ROOT / (
    "examples/team-contract-backend-config-resolver-file/create_resolver_config.py"
)
RESOLVER_ADAPTER = ROOT / (
    "examples/team-contract-backend-config-resolver-file/"
    "file_backend_config_resolver_adapter.py"
)
sys.path.insert(0, str(TOOLS))
import team_contract_backend_config_resolver as resolver_tool  # noqa: E402


class BackendConfigResolverTests(unittest.TestCase):
    @staticmethod
    def invoke(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *arguments], check=False,
            capture_output=True, text=True, timeout=30,
        )

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def backend(self, root: Path, name: str, backend_id: str,
                root_environment: str) -> Path:
        adapter = root / f"{name}-backend-adapter.py"
        shutil.copyfile(BACKEND_ADAPTER, adapter)
        output = root / f"{name}-backend.json"
        result = self.invoke(
            str(BACKEND_GENERATOR),
            "--python", str(Path(sys.executable).resolve()),
            "--adapter", str(adapter.resolve()),
            "--backend-id", backend_id,
            "--authority-id", "portable-authority",
            "--registry-id", "portable-registry",
            "--root-environment", root_environment,
            "--output", str(output.resolve()),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return output

    def resolver(self, root: Path, name: str, backend: Path) \
            -> tuple[Path, Path]:
        adapter = root / f"{name}-resolver-adapter.py"
        shutil.copyfile(RESOLVER_ADAPTER, adapter)
        mapping = root / f"{name}-mapping.json"
        config = root / f"{name}-resolver.json"
        result = self.invoke(
            str(RESOLVER_GENERATOR),
            "--python", str(Path(sys.executable).resolve()),
            "--adapter", str(adapter.resolve()),
            "--resolver-id", "portable-backends",
            "--entry", "primary", "deploy-2026-08", str(backend.resolve()),
            "--mapping-output", str(mapping.resolve()),
            "--output", str(config.resolve()),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return config, mapping

    def test_pinned_resolver_supports_portable_references_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host_a = root / "host-a"
            host_b = root / "host-b"
            host_a.mkdir()
            host_b.mkdir()
            backend_a = self.backend(
                host_a, "primary", "shared-primary", "PDR_HOST_A_BACKEND_ROOT"
            )
            backend_b = self.backend(
                host_b, "primary", "shared-primary", "PDR_HOST_B_BACKEND_ROOT"
            )
            resolver_a, mapping_a = self.resolver(host_a, "local", backend_a)
            resolver_b, _ = self.resolver(host_b, "local", backend_b)
            reference = {
                "kind": "backend-config-ref",
                "resolverId": "portable-backends", "configId": "primary",
                "backendId": "shared-primary", "revision": "deploy-2026-08",
            }
            reference_path = root / "reference.json"
            reference_path.write_text(
                json.dumps(reference, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            first = resolver_tool.ExternalCommandBackendConfigResolver(
                resolver_a, self.digest(resolver_a)
            )
            second = resolver_tool.ExternalCommandBackendConfigResolver(
                resolver_b, self.digest(resolver_b)
            )
            resolved_a = first.resolve(
                reference, "portable-authority", "portable-registry"
            )
            resolved_b = second.resolve(
                reference, "portable-authority", "portable-registry"
            )
            self.assertNotEqual(
                resolved_a.descriptor()["configPath"],
                resolved_b.descriptor()["configPath"],
            )
            self.assertEqual(resolved_a.backend_id, resolved_b.backend_id)
            report = root / "resolution.json"
            cli = self.invoke(
                str(PDR), "contract-package", "backend-config-resolve",
                "--config", str(resolver_a.resolve()),
                "--expected-config-sha256", self.digest(resolver_a),
                "--reference", str(reference_path.resolve()),
                "--authority-id", "portable-authority",
                "--registry-id", "portable-registry",
                "--report", str(report.resolve()),
            )
            self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
            self.assertEqual(
                json.loads(report.read_bytes())["reference"], reference
            )

            missing = dict(reference)
            missing["configId"] = "missing"
            with self.assertRaisesRegex(ValueError, "not authorized"):
                first.resolve(
                    missing, "portable-authority", "portable-registry"
                )
            wrong_revision = dict(reference)
            wrong_revision["revision"] = "deploy-2026-09"
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                first.resolve(
                    wrong_revision, "portable-authority", "portable-registry"
                )
            wrong_backend = dict(reference)
            wrong_backend["backendId"] = "different-backend"
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                first.resolve(
                    wrong_backend, "portable-authority", "portable-registry"
                )

            original = mapping_a.read_text(encoding="utf-8")
            mapping_a.write_text(original + " ", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact digest changed"):
                resolver_tool.ExternalCommandBackendConfigResolver(
                    resolver_a, self.digest(resolver_a)
                )
            print(
                "PDR_BACKEND_CONFIG_RESOLVER_PASS config=1 pins=1 "
                "capability=1 resolve=1 identity=1 revision=1 scope=1 "
                "drift=1 portableRef=1 crossHost=1 cli=1"
            )


if __name__ == "__main__":
    unittest.main()
