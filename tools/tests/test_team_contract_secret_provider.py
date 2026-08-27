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
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
PDR = TOOLS / "pdr.py"
SECRET_EXAMPLE = ROOT / "examples/team-contract-secret-provider-environment"
BACKEND_EXAMPLE = ROOT / "examples/team-contract-registry-leader-backend-file"
sys.path.insert(0, str(TOOLS))
import team_contract_registry_leader_backend as backend_tool  # noqa: E402
import team_contract_secret_provider as secret_tool  # noqa: E402


class SecretProviderTests(unittest.TestCase):
    @staticmethod
    def invoke(*arguments: str, environment=None):
        return subprocess.run(
            [sys.executable, *arguments], check=False, capture_output=True,
            text=True, timeout=30, env=environment,
        )

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_pinned_provider_redacts_and_injects_per_backend_request(self):
        sentinel = "pdr-test-secret-value-never-persisted"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            provider_adapter = work / "secret-adapter.py"
            backend_adapter = work / "backend-adapter.py"
            shutil.copyfile(
                SECRET_EXAMPLE / "environment_secret_provider_adapter.py",
                provider_adapter,
            )
            provider_adapter.write_text(
                provider_adapter.read_text(encoding="utf-8").replace(
                    "secret version changed", "provider-controlled-error-marker"
                ), encoding="utf-8",
            )
            shutil.copyfile(
                BACKEND_EXAMPLE / "file_backend_adapter.py", backend_adapter
            )
            mapping = work / "mapping.json"
            provider_config = work / "provider.json"
            generated = self.invoke(
                str(SECRET_EXAMPLE / "create_secret_provider_config.py"),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(provider_adapter.resolve()),
                "--provider-id", "test-provider",
                "--entry", "backend-auth", "v1", "PDR_TEST_SECRET_SOURCE",
                "--mapping-output", str(mapping.resolve()),
                "--output", str(provider_config.resolve()),
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            reference = {
                "kind": "secret-ref", "providerId": "test-provider",
                "secretId": "backend-auth", "version": "v1",
            }
            reference_path = work / "reference.json"
            reference_path.write_text(
                json.dumps(reference, sort_keys=True) + "\n", encoding="utf-8"
            )
            environment = dict(os.environ)
            environment["PDR_TEST_SECRET_SOURCE"] = sentinel
            legacy_mapping = work / "legacy-mapping.json"
            legacy_mapping_document = json.loads(mapping.read_bytes())
            legacy_mapping_document["schemaVersion"] = 1
            for entry in legacy_mapping_document["entries"]:
                entry.pop("status")
            legacy_mapping.write_text(
                json.dumps(legacy_mapping_document, indent=2, sort_keys=True)
                + "\n", encoding="utf-8",
            )
            legacy_config = work / "legacy-provider.json"
            legacy_config_document = json.loads(provider_config.read_bytes())
            legacy_config_document["schemaVersion"] = 1
            legacy_config_document["minimumProtocolMinor"] = 0
            legacy_config_document["requiredCapabilities"] = [
                "bounded-secret", "no-secret-persistence", "scoped-read",
                "version-pinned-read",
            ]
            legacy_config_document["environmentVariables"] = [
                "PDR_TEST_SECRET_SOURCE"
            ]
            legacy_config_document.pop("optionalEnvironmentVariables")
            legacy_config_document.pop("leasePolicy")
            legacy_config_document["arguments"] = [
                str(provider_adapter.resolve()), "--mapping",
                str(legacy_mapping.resolve()),
            ]
            for pin in legacy_config_document["artifactPins"]:
                if Path(pin["path"]) == mapping.resolve():
                    pin["path"] = str(legacy_mapping.resolve())
                    pin["sha256"] = self.digest(legacy_mapping)
            legacy_config.write_text(
                json.dumps(legacy_config_document, indent=2, sort_keys=True)
                + "\n", encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {
                "PDR_TEST_SECRET_SOURCE": sentinel,
            }, clear=False):
                legacy_provider = secret_tool.ExternalCommandSecretProvider(
                    legacy_config, self.digest(legacy_config)
                )
                self.assertEqual(legacy_provider.resolve(reference).decode(), sentinel)
            report = work / "check.json"
            checked = self.invoke(
                str(PDR), "contract-package", "secret-provider-check",
                "--config", str(provider_config.resolve()),
                "--expected-config-sha256", self.digest(provider_config),
                "--reference", str(reference_path.resolve()),
                "--expected-reference-sha256", self.digest(reference_path),
                "--report", str(report.resolve()), environment=environment,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertIn("PDR_SECRET_PROVIDER_CHECK_PASS", checked.stdout)
            durable = b"".join([
                mapping.read_bytes(), provider_config.read_bytes(),
                reference_path.read_bytes(), report.read_bytes(),
                checked.stdout.encode(), checked.stderr.encode(),
            ])
            self.assertNotIn(sentinel.encode(), durable)
            self.assertNotIn(b"secretBase64", report.read_bytes())

            backend_root = work / "backend-state"
            backend_config = work / "backend.json"
            backend_generated = self.invoke(
                str(BACKEND_EXAMPLE / "create_backend_config.py"),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(backend_adapter.resolve()),
                "--backend-id", "credential-backend",
                "--authority-id", "credential-authority",
                "--registry-id", "credential-registry",
                "--root-environment", "PDR_TEST_BACKEND_ROOT",
                "--secret-provider-config", str(provider_config.resolve()),
                "--credential", "PDR_BACKEND_AUTH_TOKEN", "backend-auth", "v1",
                "--required-environment", "PDR_BACKEND_AUTH_TOKEN",
                "--output", str(backend_config.resolve()),
            )
            self.assertEqual(
                backend_generated.returncode, 0,
                backend_generated.stdout + backend_generated.stderr,
            )
            backend_document = json.loads(backend_config.read_bytes())
            self.assertEqual(backend_document["schemaVersion"], 3)
            self.assertNotIn("PDR_BACKEND_AUTH_TOKEN",
                             backend_document["environmentVariables"])
            self.assertNotIn(sentinel.encode(), backend_config.read_bytes())
            with mock.patch.dict(os.environ, {
                "PDR_TEST_SECRET_SOURCE": sentinel,
                "PDR_TEST_BACKEND_ROOT": str(backend_root.resolve()),
            }, clear=False):
                backend = backend_tool.ExternalCommandBackend(
                    backend_config, self.digest(backend_config),
                    "credential-authority", "credential-registry",
                )
                self.assertIsNone(backend.current())
            with mock.patch.dict(os.environ, {
                "PDR_TEST_BACKEND_ROOT": str(backend_root.resolve()),
            }, clear=True):
                backend = backend_tool.ExternalCommandBackend(
                    backend_config, self.digest(backend_config),
                    "credential-authority", "credential-registry",
                )
                with self.assertRaises((ValueError, RuntimeError)):
                    backend.current()

            with mock.patch.dict(os.environ, {
                "PDR_TEST_SECRET_SOURCE": sentinel,
            }, clear=False):
                provider = secret_tool.ExternalCommandSecretProvider(
                    provider_config, self.digest(provider_config)
                )
                provider_again = secret_tool.ExternalCommandSecretProvider(
                    provider_config, self.digest(provider_config)
                )
                self.assertEqual(
                    provider.descriptor()["capabilityManifestSha256"],
                    provider_again.descriptor()["capabilityManifestSha256"],
                )
                self.assertEqual(provider.resolve(reference).decode(), sentinel)
                wrong_version = dict(reference, version="v2")
                with self.assertRaises(RuntimeError) as rejected:
                    provider.resolve(wrong_version)
                self.assertNotIn(
                    "provider-controlled-error-marker", str(rejected.exception)
                )
                mapping.write_bytes(mapping.read_bytes() + b" ")
                with self.assertRaises(ValueError):
                    provider.resolve(reference)
        print(
            "PDR_SECRET_PROVIDER_PASS config=1 pins=1 capability=1 resolve=1 "
            "version=1 scope=1 missing=1 drift=1 noPersistence=1 redaction=1 "
            "cli=1 backendInjection=1 failClosed=1 compatibilityV1=1"
        )

    def test_leased_rotation_fallback_revocation_and_backend_v4(self):
        old_value = "old-credential-value"
        new_value = "new-credential-value"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            provider_adapter = work / "secret-adapter.py"
            backend_adapter = work / "backend-adapter.py"
            shutil.copyfile(
                SECRET_EXAMPLE / "environment_secret_provider_adapter.py",
                provider_adapter,
            )
            shutil.copyfile(
                BACKEND_EXAMPLE / "file_backend_adapter.py", backend_adapter
            )

            def provider_config(name: str, *extra: str) -> Path:
                config = work / f"{name}-provider.json"
                mapping = work / f"{name}-mapping.json"
                result = self.invoke(
                    str(SECRET_EXAMPLE / "create_secret_provider_config.py"),
                    "--python", str(Path(sys.executable).resolve()),
                    "--adapter", str(provider_adapter.resolve()),
                    "--provider-id", "rotation-provider",
                    "--entry", "backend-auth", "v2", "PDR_ROTATE_NEW",
                    "--entry", "backend-auth", "v1", "PDR_ROTATE_OLD",
                    "--mapping-output", str(mapping.resolve()),
                    *extra, "--output", str(config.resolve()),
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return config

            config = provider_config("active")
            provider = secret_tool.ExternalCommandSecretProvider(
                config, self.digest(config)
            )
            future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
            past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            reference = {
                "kind": "secret-rotation-ref",
                "providerId": "rotation-provider", "secretId": "backend-auth",
                "versions": ["v2", "v1"], "fallbackUntil": future,
            }
            base_environment = {
                name: os.environ[name] for name in ("SystemRoot", "WINDIR")
                if name in os.environ
            }
            with mock.patch.dict(os.environ, {
                **base_environment, "PDR_ROTATE_OLD": old_value,
            }, clear=True):
                fallback = provider.lease(reference)
                self.assertEqual(fallback.selected_version, "v1")
                self.assertEqual(fallback.value.decode(), old_value)
                self.assertGreaterEqual(fallback.remaining_seconds(), 5)
            with mock.patch.dict(os.environ, {
                **base_environment, "PDR_ROTATE_OLD": old_value,
                "PDR_ROTATE_NEW": new_value,
            }, clear=True):
                preferred = provider.lease(reference)
                self.assertEqual(preferred.selected_version, "v2")
                self.assertEqual(preferred.value.decode(), new_value)
            expired_reference = dict(reference, fallbackUntil=past)
            with mock.patch.dict(os.environ, {
                **base_environment, "PDR_ROTATE_OLD": old_value,
            }, clear=True):
                with self.assertRaises(RuntimeError):
                    provider.lease(expired_reference)

            revoked_config = provider_config(
                "revoked", "--revoked", "backend-auth", "v2"
            )
            revoked_provider = secret_tool.ExternalCommandSecretProvider(
                revoked_config, self.digest(revoked_config)
            )
            with mock.patch.dict(os.environ, {
                **base_environment, "PDR_ROTATE_OLD": old_value,
                "PDR_ROTATE_NEW": new_value,
            }, clear=True):
                revoked = revoked_provider.lease(reference)
                self.assertEqual(revoked.selected_version, "v1")

            backend_config = work / "backend-v4.json"
            generated = self.invoke(
                str(BACKEND_EXAMPLE / "create_backend_config.py"),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(backend_adapter.resolve()),
                "--backend-id", "rotation-backend",
                "--authority-id", "rotation-authority",
                "--registry-id", "rotation-registry",
                "--root-environment", "PDR_ROTATION_BACKEND_ROOT",
                "--secret-provider-config", str(config.resolve()),
                "--rotating-credential", "PDR_BACKEND_AUTH_TOKEN",
                "backend-auth", "v2", "v1", future,
                "--required-environment", "PDR_BACKEND_AUTH_TOKEN",
                "--minimum-credential-lease-seconds", "10",
                "--output", str(backend_config.resolve()),
            )
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            backend_document = json.loads(backend_config.read_bytes())
            self.assertEqual(backend_document["schemaVersion"], 4)
            self.assertEqual(backend_document["minimumCredentialLeaseSeconds"], 10)
            backend_environment = {
                **base_environment, "PDR_ROTATE_OLD": old_value,
                "PDR_ROTATION_BACKEND_ROOT": str((work / "state").resolve()),
            }
            with mock.patch.dict(os.environ, backend_environment, clear=True):
                backend = backend_tool.ExternalCommandBackend(
                    backend_config, self.digest(backend_config),
                    "rotation-authority", "rotation-registry",
                )
                self.assertIsNone(backend.current())

            short_config = provider_config(
                "short", "--lease-seconds", "6",
                "--minimum-remaining-seconds", "1",
            )
            short_backend_config = work / "short-backend-v4.json"
            short_generated = self.invoke(
                str(BACKEND_EXAMPLE / "create_backend_config.py"),
                "--python", str(Path(sys.executable).resolve()),
                "--adapter", str(backend_adapter.resolve()),
                "--backend-id", "short-lease-backend",
                "--authority-id", "rotation-authority",
                "--registry-id", "rotation-registry",
                "--root-environment", "PDR_ROTATION_BACKEND_ROOT",
                "--secret-provider-config", str(short_config.resolve()),
                "--rotating-credential", "PDR_BACKEND_AUTH_TOKEN",
                "backend-auth", "v2", "v1", future,
                "--required-environment", "PDR_BACKEND_AUTH_TOKEN",
                "--minimum-credential-lease-seconds", "10",
                "--output", str(short_backend_config.resolve()),
            )
            self.assertEqual(short_generated.returncode, 0, short_generated.stderr)
            with mock.patch.dict(os.environ, backend_environment, clear=True):
                short_backend = backend_tool.ExternalCommandBackend(
                    short_backend_config, self.digest(short_backend_config),
                    "rotation-authority", "rotation-registry",
                )
                with self.assertRaises(ValueError):
                    short_backend.current()
        print(
            "PDR_SECRET_ROTATION_PASS lease=1 preferred=1 rotation=1 "
            "fallback=1 fallbackDeadline=1 revocation=1 backendV4=1 "
            "backendLease=1 optionalSource=1"
        )


if __name__ == "__main__":
    unittest.main()
