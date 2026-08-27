#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import team_contract_adapter_certifier_signer as signer_tool
import team_contract_package as package_tool


class CertifierSignerTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        print(
            "PDR_ADAPTER_CERTIFIER_SIGNER_PASS protocol=1 capability=1 "
            "external=1 keyRouting=1 payloadPin=1 configPin=1 artifactPin=1 "
            "environment=1 signatureVerify=1 rejection=1 redaction=1"
        )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        from cryptography.hazmat.primitives.asymmetric.ed25519 import \
            Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding, NoEncryption, PrivateFormat, PublicFormat,
        )
        private = Ed25519PrivateKey.generate()
        self.private_path = self.root / "private.pem"
        self.public_path = self.root / "public.pem"
        self.private_path.write_bytes(private.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        ))
        self.public_path.write_bytes(private.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        ))
        source_adapter = Path(__file__).resolve().parents[2] / \
            "examples/team-contract-adapter-certifier-signer-local" / \
            "local_ed25519_certifier_signer_adapter.py"
        self.adapter = self.root / "signer-adapter.py"
        shutil.copy2(source_adapter, self.adapter)
        self.mapping = self.root / "mapping.json"
        package_tool.write_json(self.mapping, {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractAdapterCertifierSignerLocalMapping",
            "signerId": "test-kms", "certifierId": "adapter-team",
            "keys": [{
                "keyId": "key-a",
                "privateKeyEnvironment": "PDR_TEST_SIGNER_PRIVATE_KEY",
            }],
        })
        self.config = self.root / "config.json"
        package_tool.write_json(self.config, {
            "schemaVersion": 1, "product": signer_tool.CONFIG_PRODUCT,
            "signerId": "test-kms", "certifierId": "adapter-team",
            "kind": "external-command", "protocolMajor": 1,
            "minimumProtocolMinor": 0,
            "requiredCapabilities": signer_tool.REQUIRED_CAPABILITIES,
            "keys": [{
                "keyId": "key-a", "algorithm": "Ed25519",
                "publicKey": str(self.public_path),
                "publicKeySha256": package_tool.sha256_file(self.public_path),
            }],
            "executable": str(Path(sys.executable).resolve()),
            "executableSha256": package_tool.sha256_file(
                Path(sys.executable).resolve()
            ),
            "arguments": [str(self.adapter), "--mapping", str(self.mapping)],
            "artifactPins": [
                {"path": str(self.adapter),
                 "sha256": package_tool.sha256_file(self.adapter)},
                {"path": str(self.mapping),
                 "sha256": package_tool.sha256_file(self.mapping)},
            ],
            "environmentVariables": [],
            "optionalEnvironmentVariables": [
                "PDR_CERTIFIER_SIGNER_FAULT", "PDR_TEST_SIGNER_PRIVATE_KEY",
            ],
            "timeoutSeconds": 2, "maxResponseBytes": 16384,
            "maxPayloadBytes": 4096,
        })
        self.config_sha = package_tool.sha256_file(self.config)
        os.environ["PDR_TEST_SIGNER_PRIVATE_KEY"] = str(self.private_path)

    def tearDown(self) -> None:
        os.environ.pop("PDR_TEST_SIGNER_PRIVATE_KEY", None)
        os.environ.pop("PDR_CERTIFIER_SIGNER_FAULT", None)
        self.temp.cleanup()

    def test_external_signer_negotiates_and_verifies_signature(self) -> None:
        signer = signer_tool.ExternalCommandCertifierSigner(
            self.config, self.config_sha
        )
        signature = signer.sign(b"pdr-adapter-attestation", "key-a")
        self.assertEqual(len(signature), 64)
        descriptor = signer.descriptor()
        self.assertEqual(descriptor["signerId"], "test-kms")
        self.assertNotIn(str(self.root), str(descriptor))
        self.assertEqual(
            set(signer.capability_manifest["capabilities"]),
            set(signer_tool.REQUIRED_CAPABILITIES),
        )

    def test_faults_and_pins_fail_closed(self) -> None:
        signer = signer_tool.ExternalCommandCertifierSigner(
            self.config, self.config_sha
        )
        for fault, message in (
                ("corrupt-signature", "verification failed"),
                ("wrong-key-id", "response is malformed"),
                ("reject", "rejected request")):
            os.environ["PDR_CERTIFIER_SIGNER_FAULT"] = fault
            with self.assertRaisesRegex((ValueError, RuntimeError), message):
                signer.sign(b"pdr-adapter-attestation", "key-a")
        os.environ.pop("PDR_CERTIFIER_SIGNER_FAULT", None)
        with self.assertRaisesRegex(ValueError, "identity is not pinned"):
            signer_tool.ExternalCommandCertifierSigner(
                self.config, "0" * 64
            )
        self.adapter.write_text("# drift\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "digest changed"):
            signer.sign(b"pdr-adapter-attestation", "key-a")


if __name__ == "__main__":
    unittest.main()
