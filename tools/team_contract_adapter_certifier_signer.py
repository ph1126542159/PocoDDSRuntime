#!/usr/bin/env python3
"""Pinned external-command signer for Adapter conformance attestations."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import uuid
from pathlib import Path
from typing import Any

import team_contract_adapter_runtime as adapter_runtime
import team_contract_package as package_tool


CONFIG_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerConfig"
REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerRequest"
RESPONSE_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerResponse"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerCapabilityManifest"
REQUIRED_CAPABILITIES = [
    "ed25519", "key-id-routing", "payload-sha256",
    "private-key-non-export",
]


def validate_config(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "signerId", "certifierId", "kind",
        "protocolMajor", "minimumProtocolMinor", "requiredCapabilities",
        "keys", "executable", "executableSha256", "arguments",
        "artifactPins", "environmentVariables",
        "optionalEnvironmentVariables", "timeoutSeconds",
        "maxResponseBytes", "maxPayloadBytes",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CONFIG_PRODUCT
            or any(package_tool.IDENTIFIER.fullmatch(str(
                document.get(name, ""))) is None
                for name in ("signerId", "certifierId"))
            or document.get("kind") != "external-command"
            or type(document.get("protocolMajor")) is not int
            or not 1 <= document["protocolMajor"] <= 65535
            or type(document.get("minimumProtocolMinor")) is not int
            or not 0 <= document["minimumProtocolMinor"] <= 65535
            or not isinstance(document.get("requiredCapabilities"), list)
            or document["requiredCapabilities"]
                != sorted(set(document["requiredCapabilities"]))
            or not document["requiredCapabilities"]
            or len(document["requiredCapabilities"]) > 32
            or any(adapter_runtime.CAPABILITY_ID.fullmatch(str(item)) is None
                   for item in document["requiredCapabilities"])
            or not isinstance(document.get("keys"), list)
            or not 1 <= len(document["keys"]) <= 32
            or not isinstance(document.get("executable"), str)
            or package_tool.SHA256.fullmatch(str(
                document.get("executableSha256", ""))) is None
            or not isinstance(document.get("arguments"), list)
            or len(document["arguments"]) > 32
            or any(not isinstance(item, str) or not item
                   or len(item) > 1024 or "\x00" in item
                   for item in document["arguments"])
            or type(document.get("timeoutSeconds")) is not int
            or not 1 <= document["timeoutSeconds"] <= 60
            or type(document.get("maxResponseBytes")) is not int
            or not 1024 <= document["maxResponseBytes"] <= 1024 * 1024
            or type(document.get("maxPayloadBytes")) is not int
            or not 256 <= document["maxPayloadBytes"] <= 64 * 1024):
        raise ValueError("Adapter certifier signer configuration is malformed")
    adapter_runtime.validate_artifact_pins(
        document["artifactPins"], "Adapter certifier signer"
    )
    adapter_runtime.validate_environment_policy(
        document["environmentVariables"],
        optional=document["optionalEnvironmentVariables"],
        label="Adapter certifier signer",
    )
    seen: set[str] = set()
    for item in document["keys"]:
        if (not isinstance(item, dict) or set(item) != {
                "keyId", "algorithm", "publicKey", "publicKeySha256"
                } or package_tool.IDENTIFIER.fullmatch(str(
                    item.get("keyId", ""))) is None
                or item.get("algorithm") != "Ed25519"
                or not isinstance(item.get("publicKey"), str)
                or package_tool.SHA256.fullmatch(str(
                    item.get("publicKeySha256", ""))) is None
                or item["keyId"] in seen):
            raise ValueError("Adapter certifier signer key is malformed")
        seen.add(item["keyId"])


def load_config(path_value: str | Path, expected_sha256: str) \
        -> tuple[dict[str, Any], Path, str]:
    config, path, digest = adapter_runtime.load_pinned_json(
        path_value, expected_sha256, "Adapter certifier signer",
        validate_config,
    )
    adapter_runtime.revalidate_artifacts(config, "Adapter certifier signer")
    for item in config["keys"]:
        adapter_runtime.regular_pinned_file(
            item["publicKey"], item["publicKeySha256"],
            "Adapter certifier signer public key",
        )
    return config, path, digest


def capability_request(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": CAPABILITY_REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "signerId": config["signerId"],
        "certifierId": config["certifierId"],
    }


def validate_capability_manifest(document: Any,
                                 request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "signerId",
        "certifierId", "implementationId", "protocolMajor",
        "protocolMinor", "capabilities", "keyIds",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CAPABILITY_MANIFEST_PRODUCT
            or any(document.get(name) != request[name]
                   for name in ("requestId", "signerId", "certifierId"))
            or package_tool.IDENTIFIER.fullmatch(str(
                document.get("implementationId", ""))) is None
            or type(document.get("protocolMajor")) is not int
            or type(document.get("protocolMinor")) is not int
            or not isinstance(document.get("capabilities"), list)
            or document["capabilities"]
                != sorted(set(document["capabilities"]))
            or not document["capabilities"]
            or any(adapter_runtime.CAPABILITY_ID.fullmatch(str(item)) is None
                   for item in document["capabilities"])
            or not isinstance(document.get("keyIds"), list)
            or document["keyIds"] != sorted(set(document["keyIds"]))
            or not document["keyIds"]
            or any(package_tool.IDENTIFIER.fullmatch(str(item)) is None
                   for item in document["keyIds"])):
        raise ValueError(
            "Adapter certifier signer capability manifest is malformed"
        )


def sign_request(config: dict[str, Any], key_id: str,
                 payload: bytes) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "signerId": config["signerId"],
        "certifierId": config["certifierId"], "operation": "sign",
        "purpose": "adapter-conformance-attestation", "keyId": key_id,
        "algorithm": "Ed25519",
        "payloadBase64": base64.b64encode(payload).decode("ascii"),
        "payloadSha256": package_tool.sha256_bytes(payload),
    }


def response_signature(document: Any, request: dict[str, Any]) -> bytes:
    fields = {
        "schemaVersion", "product", "requestId", "signerId",
        "certifierId", "operation", "purpose", "keyId", "algorithm",
        "passed", "signatureBase64", "errorCode",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != RESPONSE_PRODUCT
            or any(document.get(name) != request[name] for name in (
                "requestId", "signerId", "certifierId", "operation",
                "purpose", "keyId", "algorithm",
            )) or type(document.get("passed")) is not bool):
        raise ValueError("Adapter certifier signer response is malformed")
    if not document["passed"]:
        if (document.get("signatureBase64") is not None
                or document.get("errorCode") not in {
                    "key-unavailable", "policy-denied", "signing-failed"
                }):
            raise ValueError("Adapter certifier signer rejection is malformed")
        raise RuntimeError("Adapter certifier signer rejected request")
    if document.get("errorCode") is not None:
        raise ValueError("Adapter certifier signer success is malformed")
    try:
        signature = base64.b64decode(
            document.get("signatureBase64"), validate=True
        )
    except (TypeError, ValueError, binascii.Error) as error:
        raise ValueError(
            "Adapter certifier signer signature encoding is invalid"
        ) from error
    if len(signature) != 64:
        raise ValueError("Adapter certifier signer signature is invalid")
    return signature


class ExternalCommandCertifierSigner:
    def __init__(self, config_path: str | Path,
                 expected_config_sha256: str) -> None:
        self.config, self.config_path, self.config_sha256 = load_config(
            config_path, expected_config_sha256
        )
        request = capability_request(self.config)
        manifest = self._invoke(request, configured_environment=False)
        validate_capability_manifest(manifest, request)
        adapter_runtime.enforce_capability_policy(
            self.config, manifest, "Adapter certifier signer"
        )
        expected_keys = sorted(item["keyId"] for item in self.config["keys"])
        if manifest["keyIds"] != expected_keys:
            raise ValueError("Adapter certifier signer key identity changed")
        self.capability_manifest = manifest
        self.capability_manifest_sha256 = adapter_runtime.capability_digest(
            manifest, "signerId"
        )

    @property
    def signer_id(self) -> str:
        return str(self.config["signerId"])

    @property
    def certifier_id(self) -> str:
        return str(self.config["certifierId"])

    def descriptor(self) -> dict[str, str]:
        return {
            "signerId": self.signer_id,
            "signerConfigSha256": self.config_sha256,
            "signerCapabilityManifestSha256":
                self.capability_manifest_sha256,
        }

    def _invoke(self, request: dict[str, Any], *,
                configured_environment: bool = True) -> dict[str, Any]:
        config, path, digest = load_config(
            self.config_path, self.config_sha256
        )
        if config != self.config or path != self.config_path \
                or digest != self.config_sha256:
            raise ValueError("Adapter certifier signer configuration changed")
        environment = adapter_runtime.isolated_environment(
            config["environmentVariables"],
            optional=config["optionalEnvironmentVariables"],
            require_required=configured_environment,
            label="Adapter certifier signer",
        )
        command = [str(Path(config["executable"]).resolve()),
                   *config["arguments"]]
        return adapter_runtime.invoke_json(
            command, request, environment=environment,
            timeout_seconds=config["timeoutSeconds"],
            max_response_bytes=config["maxResponseBytes"],
            label="Adapter certifier signer", expose_stderr=False,
        )

    def sign(self, payload: bytes, key_id: str) -> bytes:
        if (not isinstance(payload, bytes)
                or not 1 <= len(payload) <= self.config["maxPayloadBytes"]
                or package_tool.IDENTIFIER.fullmatch(str(key_id)) is None):
            raise ValueError("Adapter certifier signer request is malformed")
        key = next((item for item in self.config["keys"]
                    if item["keyId"] == key_id), None)
        if key is None:
            raise ValueError("Adapter certifier signer key is not configured")
        request = sign_request(self.config, key_id, payload)
        signature = response_signature(self._invoke(request), request)
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import \
                Ed25519PublicKey
            from cryptography.hazmat.primitives.serialization import \
                load_pem_public_key
            public = load_pem_public_key(Path(key["publicKey"]).read_bytes())
            if not isinstance(public, Ed25519PublicKey):
                raise ValueError("Signer public key is not Ed25519")
            public.verify(signature, payload)
        except Exception as error:
            raise ValueError(
                "Adapter certifier signer signature verification failed"
            ) from error
        return signature


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--self-check", action="store_true",
        help="verify that the installed Certifier Signer host can load",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    if args.self_check:
        print(
            "PDR_ADAPTER_CERTIFIER_SIGNER_SELF_CHECK_PASS "
            "protocol=1 pins=1 isolation=1 verification=1"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
