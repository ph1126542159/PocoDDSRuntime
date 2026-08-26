#!/usr/bin/env python3

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "team_contract_package.py"
PDR = TOOL.with_name("pdr.py")


class TeamContractPackageTests(unittest.TestCase):
    def run_tool(self, *arguments: str,
                 environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *arguments],
            check=False, capture_output=True, text=True, env=environment,
        )

    @staticmethod
    def write_team(root: Path, prefix: str) -> dict[str, Path]:
        root.mkdir(parents=True)
        documents = {
            "service-contract": {
                "schemaVersion": 1,
                "provides": [{
                    "contract": f"{prefix}.scheduler", "version": "1.0.0",
                    "serviceName": f"{prefix}.service.scheduler",
                }],
                "requires": [],
            },
            "participant-declaration": {
                "schemaVersion": 1,
                "participants": [{
                    "id": f"{prefix}-configuration",
                    "serviceName": f"{prefix}.configuration.participant",
                    "ownedPrefixes": [f"{prefix}.configuration"], "after": [],
                }],
            },
            "key-lifecycle": {"schemaVersion": 1, "entries": []},
        }
        paths: dict[str, Path] = {}
        for role, document in documents.items():
            path = root / f"renamed-{role}.json"
            path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            paths[role] = path
        return paths

    def pack(self, output: Path, package_id: str, owner: str,
             inputs: dict[str, Path]) -> subprocess.CompletedProcess[str]:
        command = [
            "pack", "--package-id", package_id, "--version", "1.2.3",
            "--owner", owner, "--output", str(output),
            "--source-date-epoch", "1700000000",
        ]
        for role, path in reversed(list(inputs.items())):
            command.extend(["--input", f"{role}={path}"])
        return self.run_tool(*command)

    @staticmethod
    def signing_fixture(root: Path, revoked: bool = False,
                        not_after: str = "2030-01-01T00:00:00Z") -> tuple[Path, Path, str]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        trust = root / "trust"
        keys = trust / "keys"
        keys.mkdir(parents=True)
        private_key = trust / "test-private.pem"
        public_key = keys / "team-alpha.pem"
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
        private_key.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        public_key.write_bytes(key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        policy = trust / "team-contract-trust-policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractTrustPolicy",
            "policyId": "product-team-contracts",
            "allowedPublishers": [{
                "owner": "team.alpha",
                "keyId": "team-alpha-2026",
                "algorithm": "Ed25519",
                "publicKey": "keys/team-alpha.pem",
                "publicKeySha256": hashlib.sha256(public_key.read_bytes()).hexdigest(),
                "packageIds": ["team.alpha"],
                "notBefore": "2025-01-01T00:00:00Z",
                "notAfter": not_after,
            }],
            "revokedKeys": ([{
                "keyId": "team-alpha-2026",
                "revokedAt": "2026-08-01T00:00:00Z",
                "reason": "unit test revocation",
            }] if revoked else []),
        }, indent=2) + "\n", encoding="utf-8")
        return private_key, policy, hashlib.sha256(policy.read_bytes()).hexdigest()

    def pack_signed(self, output: Path, inputs: dict[str, Path],
                    private_key: Path) -> subprocess.CompletedProcess[str]:
        environment_name = "PDR_TEST_TEAM_CONTRACT_PRIVATE_KEY"
        environment = dict(os.environ, **{environment_name: str(private_key)})
        command = [
            "pack", "--package-id", "team.alpha", "--version", "1.2.3",
            "--owner", "team.alpha", "--output", str(output),
            "--source-date-epoch", "1700000000",
            "--ed25519-private-key-environment", environment_name,
            "--signing-key-id", "team-alpha-2026",
        ]
        for role, path in inputs.items():
            command.extend(["--input", f"{role}={path}"])
        return self.run_tool(*command, environment=environment)

    def test_two_team_packages_are_path_independent_locked_and_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alpha_inputs = self.write_team(root / "alpha/source", "alpha")
            beta_inputs = self.write_team(root / "beta/source", "beta")
            alpha = root / "dist/alpha.pdrcontracts"
            alpha_copy = root / "moved/provider-alpha-renamed.pdrcontracts"
            beta = root / "dist/beta.pdrcontracts"
            alpha.parent.mkdir(parents=True)
            alpha_copy.parent.mkdir(parents=True)
            self.assertEqual(self.pack(alpha, "team.alpha", "team/alpha".replace("/", "."),
                                       alpha_inputs).returncode, 0)
            self.assertEqual(self.pack(beta, "team.beta", "team.beta", beta_inputs).returncode, 0)

            relocated_inputs = self.write_team(root / "relocated/alpha", "alpha")
            self.assertEqual(self.pack(alpha_copy, "team.alpha", "team.alpha",
                                       relocated_inputs).returncode, 0)
            self.assertEqual(alpha.read_bytes(), alpha_copy.read_bytes())

            lock = root / "consumer/team-contracts.lock.json"
            locked = self.run_tool(
                "lock", "--package", str(beta), "--package", str(alpha),
                "--output", str(lock),
            )
            self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
            lock_document = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(
                [item["packageId"] for item in lock_document["packages"]],
                ["team.alpha", "team.beta"],
            )
            self.assertNotIn(str(root), lock.read_text(encoding="utf-8"))

            output = root / "consumer/resolved"
            report = root / "consumer/resolution.json"
            resolved = self.run_tool(
                "resolve", "--lock", str(lock), "--package", str(alpha_copy),
                "--package", str(beta), "--output", str(output), "--report", str(report),
            )
            self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertEqual(len(evidence["packages"]), 2)
            for package in evidence["packages"]:
                for item in package["files"]:
                    path = output / item["path"]
                    self.assertTrue(path.is_file())
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])

    def test_tamper_and_stale_lock_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self.write_team(root / "source", "alpha")
            package = root / "alpha.pdrcontracts"
            self.assertEqual(self.pack(package, "team.alpha", "team.alpha", inputs).returncode, 0)
            lock = root / "team-contracts.lock.json"
            self.assertEqual(self.run_tool(
                "lock", "--package", str(package), "--output", str(lock)
            ).returncode, 0)

            tampered = root / "tampered.pdrcontracts"
            with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
                for info in source.infolist():
                    content = source.read(info)
                    if info.filename.startswith("contracts/service-contract/"):
                        content += b" "
                    target.writestr(info, content)
            rejected = self.run_tool("verify", str(tampered))
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("entry changed", rejected.stderr)

            trailing = root / "trailing-data.pdrcontracts"
            trailing.write_bytes(package.read_bytes() + b"unsigned-trailing-data")
            trailing_rejected = self.run_tool("verify", str(trailing))
            self.assertNotEqual(trailing_rejected.returncode, 0)
            self.assertIn("after the ZIP end record", trailing_rejected.stderr)

            changed = dict(inputs)
            service = json.loads(changed["service-contract"].read_text(encoding="utf-8"))
            service["provides"][0]["version"] = "1.1.0"
            changed["service-contract"].write_text(
                json.dumps(service, indent=2) + "\n", encoding="utf-8"
            )
            replacement = root / "replacement.pdrcontracts"
            self.assertEqual(self.pack(
                replacement, "team.alpha", "team.alpha", changed
            ).returncode, 0)
            stale = self.run_tool(
                "resolve", "--lock", str(lock), "--package", str(replacement),
                "--output", str(root / "resolved"),
            )
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("does not match lock", stale.stderr)

    def test_unsafe_archive_entry_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "unsafe.pdrcontracts"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("../escape.json", "{}")
            result = self.run_tool("verify", str(package))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsafe contract package entry", result.stderr)

    def test_unified_pdr_frontend_verifies_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self.write_team(root / "source", "frontend")
            package = root / "frontend.pdrcontracts"
            self.assertEqual(self.pack(
                package, "team.frontend", "team.frontend", inputs
            ).returncode, 0)
            report = root / "verify.json"
            result = subprocess.run(
                [sys.executable, str(PDR), "contract-package", "verify", str(package),
                 "--report", str(report)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json.loads(report.read_text(encoding="utf-8"))["passed"])

    def test_ed25519_trust_is_bound_into_lock_and_rechecked_on_resolve(self):
        try:
            import cryptography  # noqa: F401
        except ImportError:
            self.skipTest("cryptography is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self.write_team(root / "source", "alpha")
            private_key, policy, policy_sha = self.signing_fixture(root)
            package = root / "team-alpha.pdrcontracts"
            self.assertEqual(self.pack_signed(
                package, inputs, private_key
            ).returncode, 0)
            common = [
                "--require-signature", "--trust-policy", str(policy),
                "--expected-trust-policy-id", "product-team-contracts",
                "--expected-trust-policy-sha256", policy_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
            ]
            verified = self.run_tool("verify", str(package), *common)
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

            lock = root / "team-contracts.lock.json"
            locked = self.run_tool(
                "lock", "--package", str(package), "--output", str(lock), *common
            )
            self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
            lock_document = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(lock_document["trustPolicy"]["policySha256"], policy_sha)
            self.assertEqual(
                lock_document["packages"][0]["signature"]["keyId"], "team-alpha-2026"
            )
            self.assertNotIn("keys/team-alpha.pem", lock.read_text(encoding="utf-8"))

            moved = root / "cache/renamed-alpha.pdrcontracts"
            moved.parent.mkdir()
            moved.write_bytes(package.read_bytes())
            report = root / "resolution.json"
            resolved = self.run_tool(
                "resolve", "--lock", str(lock), "--package", str(moved),
                "--output", str(root / "resolved"), "--report", str(report), *common
            )
            self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(evidence["trustPolicy"]["policySha256"], policy_sha)
            self.assertEqual(
                evidence["packages"][0]["signature"]["publicKeySha256"],
                lock_document["packages"][0]["signature"]["publicKeySha256"],
            )

    def test_revoked_expired_tampered_and_unsigned_publishers_are_rejected(self):
        try:
            import cryptography  # noqa: F401
        except ImportError:
            self.skipTest("cryptography is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self.write_team(root / "source", "alpha")
            private_key, policy, policy_sha = self.signing_fixture(root)
            package = root / "team-alpha.pdrcontracts"
            self.assertEqual(self.pack_signed(package, inputs, private_key).returncode, 0)

            _, revoked_policy, revoked_sha = self.signing_fixture(root / "revoked", revoked=True)
            revoked = self.run_tool(
                "verify", str(package), "--require-signature",
                "--trust-policy", str(revoked_policy),
                "--expected-trust-policy-id", "product-team-contracts",
                "--expected-trust-policy-sha256", revoked_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
            )
            self.assertNotEqual(revoked.returncode, 0)
            self.assertIn("signing key is revoked", revoked.stderr)

            _, expired_policy, expired_sha = self.signing_fixture(
                root / "expired", not_after="2026-01-01T00:00:00Z"
            )
            expired = self.run_tool(
                "verify", str(package), "--require-signature",
                "--trust-policy", str(expired_policy),
                "--expected-trust-policy-id", "product-team-contracts",
                "--expected-trust-policy-sha256", expired_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
            )
            self.assertNotEqual(expired.returncode, 0)
            self.assertIn("validity window", expired.stderr)

            _, wrong_key_policy, _ = self.signing_fixture(root / "wrong-key")
            wrong_key_document = json.loads(wrong_key_policy.read_text(encoding="utf-8"))
            wrong_key_document["allowedPublishers"][0]["publicKeySha256"] = "0" * 64
            wrong_key_policy.write_text(
                json.dumps(wrong_key_document, indent=2) + "\n", encoding="utf-8"
            )
            wrong_key_sha = hashlib.sha256(wrong_key_policy.read_bytes()).hexdigest()
            wrong_key = self.run_tool(
                "verify", str(package), "--require-signature",
                "--trust-policy", str(wrong_key_policy),
                "--expected-trust-policy-id", "product-team-contracts",
                "--expected-trust-policy-sha256", wrong_key_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
            )
            self.assertNotEqual(wrong_key.returncode, 0)
            self.assertIn("public key SHA-256 is not trusted", wrong_key.stderr)

            tampered = root / "tampered-signature.pdrcontracts"
            with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
                for info in source.infolist():
                    content = source.read(info)
                    if info.filename == "metadata/team-contract-package.sig.json":
                        document = json.loads(content)
                        raw = bytearray(__import__("base64").b64decode(document["signature"]))
                        raw[0] ^= 1
                        document["signature"] = __import__("base64").b64encode(raw).decode()
                        content = (json.dumps(document, indent=2) + "\n").encode()
                    target.writestr(info, content)
            tamper_result = self.run_tool(
                "verify", str(tampered), "--require-signature",
                "--trust-policy", str(policy),
                "--expected-trust-policy-id", "product-team-contracts",
                "--expected-trust-policy-sha256", policy_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
            )
            self.assertNotEqual(tamper_result.returncode, 0)
            self.assertIn("Ed25519 verification failed", tamper_result.stderr)

            unsigned = root / "unsigned.pdrcontracts"
            self.assertEqual(self.pack(
                unsigned, "team.alpha", "team.alpha", inputs
            ).returncode, 0)
            unsigned_result = self.run_tool(
                "verify", str(unsigned), "--require-signature",
                "--trust-policy", str(policy),
                "--expected-trust-policy-id", "product-team-contracts",
                "--expected-trust-policy-sha256", policy_sha,
                "--verification-time", "2026-08-25T12:00:00Z",
            )
            self.assertNotEqual(unsigned_result.returncode, 0)
            self.assertIn("signature is required", unsigned_result.stderr)


if __name__ == "__main__":
    unittest.main()
