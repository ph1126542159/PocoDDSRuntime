import argparse
import json
import os
import tempfile
import unittest
import zipfile
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import plugin_manager


def make_bundle(path: Path, symbolic: str, version: str,
                dependencies: list[tuple[str, str]] | None = None,
                unsafe_name: str | None = None,
                api_version: str = "1.0.0",
                abi_version: str = "1.0.0",
                abi_fingerprint: str = "MSVC-19-Windows_NT-AMD64",
                runtime_range: str = "[0.1.0,0.2.0)") -> Path:
    require = ""
    if dependencies:
        require = "Require-Bundle: " + ", ".join(
            f"{name};bundle-version={versions}" for name, versions in dependencies
        ) + "\n"
    manifest = (
        "Manifest-Version: 1.0\n"
        f"Bundle-Name: {symbolic}\n"
        f"Bundle-SymbolicName: {symbolic}\n"
        f"Bundle-Version: {version}\n"
        f"PDR-Plugin-API: {api_version}\n"
        f"PDR-Plugin-ABI: {abi_version}\n"
        f"PDR-Plugin-ABI-Fingerprint: {abi_fingerprint}\n"
        f"PDR-Runtime-Version: {runtime_range}\n"
        f"{require}"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/manifest.mf", manifest)
        archive.writestr(unsafe_name or "bin/Windows_NT/AMD64/plugin.dll", b"plugin-code")
    return path


def make_contract(bundles: Path) -> Path:
    path = bundles.parent / plugin_manager.CONTRACT_FILE
    path.write_text(plugin_manager.json.dumps({
        "schemaVersion": 1,
        "runtimeVersion": "0.1.0",
        "pluginApiVersion": "1.0.0",
        "pluginAbiVersion": "1.0.0",
        "abiFingerprint": "MSVC-19-Windows_NT-AMD64",
        "targetOs": "Windows_NT",
        "targetArch": "AMD64",
        "compilerId": "MSVC",
        "compilerMajor": "19",
    }), encoding="utf-8")
    return path


class PluginManagerTest(unittest.TestCase):
    def test_preflight_validates_dependency_presence_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundles = root / "bundles"
            bundles.mkdir()
            make_contract(bundles)
            make_bundle(bundles / "osp.core_1.7.0.bndl", "osp.core", "1.7.0")
            artifact = make_bundle(
                root / "pdr.plugin.sample_1.0.0.bndl", "pdr.plugin.sample", "1.0.0",
                [("osp.core", "[1.0.0,2.0.0)")],
            )
            result = plugin_manager.preflight(artifact, bundles, plugin_manager.sha256(artifact))
            self.assertTrue(result["passed"])
            self.assertTrue(result["dependencies"][0]["compatible"])

            missing = make_bundle(
                root / "pdr.plugin.missing_1.0.0.bndl", "pdr.plugin.missing", "1.0.0",
                [("pdr.not-installed", "[1.0.0,2.0.0)")],
            )
            self.assertFalse(plugin_manager.preflight(missing, bundles, None)["passed"])

    def test_rejects_path_traversal_and_non_plugin_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unsafe = make_bundle(root / "unsafe.bndl", "pdr.plugin.unsafe", "1.0.0",
                                 unsafe_name="../escape.dll")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                plugin_manager.inspect_bundle(unsafe)
            core = make_bundle(root / "core.bndl", "osp.core", "1.7.0")
            with self.assertRaisesRegex(ValueError, "only pdr.plugin"):
                plugin_manager.inspect_bundle(core)

    def test_install_upgrade_and_digest_guarded_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundles = root / "runtime" / "bundles"
            bundles.mkdir(parents=True)
            make_contract(bundles)
            make_bundle(bundles / "osp.core_1.7.0.bndl", "osp.core", "1.7.0")
            version1 = make_bundle(root / "v1.bndl", "pdr.plugin.sample", "1.0.0",
                                   [("osp.core", "[1.0.0,2.0.0)")])
            version2 = make_bundle(root / "v2.bndl", "pdr.plugin.sample", "1.1.0",
                                   [("osp.core", "[1.0.0,2.0.0)")])

            def install_args(artifact: Path) -> argparse.Namespace:
                return argparse.Namespace(
                    artifact=artifact, bundle_directory=bundles, backup_directory=None,
                    expected_sha256=plugin_manager.sha256(artifact),
                    confirm_runtime_stopped=True, audit=None, report=None,
                    allow_unsigned_plugin=True,
                )

            self.assertEqual(plugin_manager.install_plugin(install_args(version1)), 0)
            installed1 = bundles / "pdr.plugin.sample_1.0.0.bndl"
            digest1 = plugin_manager.sha256(installed1)
            self.assertEqual(plugin_manager.install_plugin(install_args(version2)), 0)
            installed2 = bundles / "pdr.plugin.sample_1.1.0.bndl"
            digest2 = plugin_manager.sha256(installed2)
            self.assertFalse(installed1.exists())

            rollback = argparse.Namespace(
                symbolic_name="pdr.plugin.sample", bundle_directory=bundles,
                backup_directory=None, expected_current_sha256=digest2,
                expected_backup_sha256=digest1, confirm_runtime_stopped=True,
                audit=None, report=None,
            )
            self.assertEqual(plugin_manager.rollback_plugin(rollback), 0)
            self.assertTrue(installed1.exists())
            self.assertFalse(installed2.exists())
            self.assertEqual(plugin_manager.sha256(installed1), digest1)

    def test_install_requires_stopped_runtime_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundles = root / "bundles"
            bundles.mkdir()
            make_contract(bundles)
            artifact = make_bundle(root / "plugin.bndl", "pdr.plugin.sample", "1.0.0")
            args = argparse.Namespace(
                artifact=artifact, bundle_directory=bundles, backup_directory=None,
                expected_sha256=plugin_manager.sha256(artifact),
                confirm_runtime_stopped=False, audit=None, report=None,
                allow_unsigned_plugin=True,
            )
            self.assertEqual(plugin_manager.install_plugin(args), 1)
            self.assertFalse((bundles / "pdr.plugin.sample_1.0.0.bndl").exists())

    def test_publish_failure_restores_old_plugin_and_clears_reconciled_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundles = root / "runtime" / "bundles"
            bundles.mkdir(parents=True)
            make_contract(bundles)
            version1 = make_bundle(root / "v1.bndl", "pdr.plugin.sample", "1.0.0")
            version2 = make_bundle(root / "v2.bndl", "pdr.plugin.sample", "1.1.0")

            def arguments(artifact: Path) -> argparse.Namespace:
                return argparse.Namespace(
                    artifact=artifact, bundle_directory=bundles, backup_directory=None,
                    expected_sha256=plugin_manager.sha256(artifact),
                    confirm_runtime_stopped=True, audit=None, report=None,
                    allow_unsigned_plugin=True,
                )

            self.assertEqual(plugin_manager.install_plugin(arguments(version1)), 0)
            original_digest = plugin_manager.sha256(
                bundles / "pdr.plugin.sample_1.0.0.bndl")
            real_replace = plugin_manager.os.replace
            failed = False

            def fail_publish(source, destination):
                nonlocal failed
                source_path = Path(source)
                destination_path = Path(destination)
                if (not failed and ".staging-" in source_path.name and
                        destination_path.name == "pdr.plugin.sample_1.1.0.bndl"):
                    failed = True
                    raise OSError("injected publish failure")
                return real_replace(source, destination)

            with mock.patch("tools.plugin_manager.os.replace", side_effect=fail_publish):
                self.assertEqual(plugin_manager.install_plugin(arguments(version2)), 1)
            restored = bundles / "pdr.plugin.sample_1.0.0.bndl"
            self.assertTrue(restored.exists())
            self.assertEqual(plugin_manager.sha256(restored), original_digest)
            self.assertFalse((root / "runtime" / ".pdr-plugin-transaction.json").exists())

    def test_existing_lock_is_not_removed_by_competing_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundles = root / "runtime" / "bundles"
            bundles.mkdir(parents=True)
            make_contract(bundles)
            lock = root / "runtime" / ".pdr-plugin.lock"
            lock.write_text("owned-by-another-process", encoding="utf-8")
            artifact = make_bundle(root / "plugin.bndl", "pdr.plugin.sample", "1.0.0")
            args = argparse.Namespace(
                artifact=artifact, bundle_directory=bundles, backup_directory=None,
                expected_sha256=plugin_manager.sha256(artifact),
                confirm_runtime_stopped=True, audit=None, report=None,
                allow_unsigned_plugin=True,
            )
            self.assertEqual(plugin_manager.install_plugin(args), 1)
            self.assertEqual(lock.read_text(encoding="utf-8"), "owned-by-another-process")

    def test_recover_restores_backup_after_interrupted_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            bundles = runtime / "bundles"
            bundles.mkdir(parents=True)
            current = make_bundle(
                bundles / "pdr.plugin.sample_1.0.0.bndl",
                "pdr.plugin.sample", "1.0.0",
            )
            current_digest = plugin_manager.sha256(current)
            transaction_id = "interrupted-install"
            backup = (runtime / "plugin-backups" / "pdr.plugin.sample" /
                      transaction_id / current.name)
            backup.parent.mkdir(parents=True)
            plugin_manager.os.replace(current, backup)
            target = bundles / "pdr.plugin.sample_1.1.0.bndl"
            stage = bundles / f".{target.name}.staging-{transaction_id}"
            stage.write_bytes(b"incomplete-stage")
            journal = runtime / ".pdr-plugin-transaction.json"
            plugin_manager.atomic_json(journal, {
                "schemaVersion": 1,
                "transactionId": transaction_id,
                "operation": "install",
                "state": "backup-created",
                "symbolicName": "pdr.plugin.sample",
                "artifactSha256": "0" * 64,
                "target": str(target),
                "stage": str(stage),
                "backup": str(backup),
                "backupSha256": current_digest,
                "previousTarget": str(current),
            })
            report = root / "recover-report.json"
            args = argparse.Namespace(
                bundle_directory=bundles, backup_directory=None,
                confirm_runtime_stopped=True, audit=None, report=report,
            )

            self.assertEqual(plugin_manager.recover_plugin(args), 0)
            self.assertTrue(current.exists())
            self.assertEqual(plugin_manager.sha256(current), current_digest)
            self.assertFalse(stage.exists())
            self.assertFalse(journal.exists())
            self.assertEqual(
                plugin_manager.json.loads(report.read_text(encoding="utf-8"))["outcome"],
                "previous-plugin-restored",
            )

    def test_preflight_rejects_api_abi_fingerprint_and_runtime_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundles = root / "runtime" / "bundles"
            bundles.mkdir(parents=True)
            make_contract(bundles)
            cases = (
                {"api_version": "2.0.0"},
                {"abi_version": "2.0.0"},
                {"abi_fingerprint": "GNU-14-Linux-x86_64"},
                {"runtime_range": "[0.2.0,0.3.0)"},
            )
            for index, overrides in enumerate(cases):
                artifact = make_bundle(
                    root / f"incompatible-{index}.bndl",
                    f"pdr.plugin.incompatible{index}", "1.0.0", **overrides,
                )
                result = plugin_manager.preflight(artifact, bundles, None)
                self.assertFalse(result["passed"])
                self.assertTrue(any(
                    not check["compatible"]
                    for check in result["pluginCompatibility"]
                ))

    def test_preflight_fails_closed_without_runtime_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundles = root / "runtime" / "bundles"
            bundles.mkdir(parents=True)
            artifact = make_bundle(
                root / "plugin.bndl", "pdr.plugin.sample", "1.0.0")
            with self.assertRaisesRegex(ValueError, "runtime plugin contract"):
                plugin_manager.preflight(artifact, bundles, None)

    def test_signed_publisher_scope_tamper_and_revocation_gates(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding, NoEncryption, PrivateFormat, PublicFormat,
            )
        except ImportError:
            self.skipTest("cryptography is unavailable on this release host")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundles = root / "runtime" / "bundles"
            bundles.mkdir(parents=True)
            make_contract(bundles)
            artifact = make_bundle(
                root / "plugin.bndl", "pdr.plugin.vendor.sample", "1.0.0")
            private_key = Ed25519PrivateKey.generate()
            private_path, public_path = root / "private.pem", root / "public.pem"
            private_path.write_bytes(private_key.private_bytes(
                Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
            public_path.write_bytes(private_key.public_key().public_bytes(
                Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
            attestation, signature = root / "attestation.json", root / "signature.json"
            sign_args = argparse.Namespace(
                artifact=artifact, publisher_id="vendor", key_id="vendor-key",
                private_key_path_environment="PDR_TEST_PLUGIN_KEY",
                private_key_passphrase_environment=None,
                attestation=attestation, signature=signature,
            )
            with mock.patch.dict(os.environ, {"PDR_TEST_PLUGIN_KEY": str(private_path)}):
                self.assertEqual(plugin_manager.sign_plugin(sign_args), 0)
            current = datetime.now(timezone.utc)
            policy_path = root / "policy.json"

            def write_policy(pattern: str, revoked: bool = False) -> str:
                policy = {
                    "schemaVersion": 1, "product": "PocoDDSRuntimePlugin",
                    "policyId": "plugin-policy",
                    "allowedPublishers": [{
                        "publisherId": "vendor", "keyId": "vendor-key",
                        "algorithm": "Ed25519",
                        "publicKeySha256": plugin_manager.sha256(public_path),
                        "pluginPatterns": [pattern],
                        "notBefore": (current - timedelta(days=1)).isoformat(),
                        "notAfter": (current + timedelta(days=1)).isoformat(),
                    }],
                    "revokedKeys": [{
                        "keyId": "vendor-key", "revokedAt": current.isoformat(),
                        "reason": "test revocation",
                    }] if revoked else [],
                }
                policy_path.write_text(json.dumps(policy), encoding="utf-8")
                return plugin_manager.sha256(policy_path)

            verifier = root / "pdr-signature-check.exe"
            verifier.write_bytes(b"trusted verifier fixture")
            args = argparse.Namespace(
                allow_unsigned_plugin=False, attestation=attestation,
                signature=signature, public_key=public_path, trust_policy=policy_path,
                expected_trust_policy_id="plugin-policy",
                expected_trust_policy_sha256=write_policy("pdr.plugin.vendor.*"),
                signature_check_executable=verifier,
            )
            info = plugin_manager.inspect_bundle(artifact)
            completed = plugin_manager.subprocess.CompletedProcess([], 0, "PASS", "")
            with mock.patch("tools.plugin_manager.subprocess.run", return_value=completed):
                evidence = plugin_manager.verify_plugin_provenance(info, args)
            self.assertTrue(evidence["verified"])
            self.assertEqual(evidence["publisherId"], "vendor")

            args.expected_trust_policy_sha256 = write_policy("pdr.plugin.other.*")
            with self.assertRaisesRegex(ValueError, "not allowed for this symbolic name"):
                plugin_manager.verify_plugin_provenance(info, args)

            args.expected_trust_policy_sha256 = write_policy("pdr.plugin.vendor.*", revoked=True)
            with self.assertRaisesRegex(ValueError, "revoked"):
                plugin_manager.verify_plugin_provenance(info, args)

            replacement = make_bundle(
                root / "replacement.bndl", "pdr.plugin.vendor.sample", "1.0.0",
                unsafe_name="bin/Windows_NT/AMD64/replacement.dll")
            args.expected_trust_policy_sha256 = write_policy("pdr.plugin.vendor.*")
            with self.assertRaisesRegex(ValueError, "does not match the artifact"):
                plugin_manager.verify_plugin_provenance(
                    plugin_manager.inspect_bundle(replacement), args)


if __name__ == "__main__":
    unittest.main()
