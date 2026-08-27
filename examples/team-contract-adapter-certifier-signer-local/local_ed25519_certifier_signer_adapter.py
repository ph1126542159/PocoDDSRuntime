#!/usr/bin/env python3
"""Reference external-command Ed25519 certifier signer for SDK tests."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


MAPPING_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerLocalMapping"
REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerRequest"
RESPONSE_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerResponse"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerCapabilityManifest"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITIES = [
    "ed25519", "key-id-routing", "payload-sha256",
    "private-key-non-export",
]


def load_mapping(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("signer mapping must be an absolute non-link file")
    document = json.loads(path.read_bytes())
    if (not isinstance(document, dict) or set(document) != {
            "schemaVersion", "product", "signerId", "certifierId", "keys"
            } or document.get("schemaVersion") != 1
            or document.get("product") != MAPPING_PRODUCT
            or any(IDENTIFIER.fullmatch(str(document.get(name, ""))) is None
                   for name in ("signerId", "certifierId"))
            or not isinstance(document.get("keys"), list)
            or not 1 <= len(document["keys"]) <= 32):
        raise ValueError("signer mapping is malformed")
    seen: set[str] = set()
    for key in document["keys"]:
        if (not isinstance(key, dict) or set(key) != {
                "keyId", "privateKeyEnvironment"
                } or IDENTIFIER.fullmatch(str(key.get("keyId", ""))) is None
                or ENVIRONMENT_NAME.fullmatch(str(
                    key.get("privateKeyEnvironment", ""))) is None
                or key["keyId"] in seen):
            raise ValueError("signer mapping key is malformed")
        seen.add(key["keyId"])
    return document


def read_request() -> dict[str, Any]:
    content = sys.stdin.buffer.read(1024 * 1024 + 1)
    if not 1 <= len(content) <= 1024 * 1024:
        raise ValueError("signer request size is outside policy")
    document = json.loads(content)
    if not isinstance(document, dict):
        raise ValueError("signer request must be an object")
    return document


def capability(request: dict[str, Any], mapping: dict[str, Any]) \
        -> dict[str, Any]:
    if (set(request) != {
            "schemaVersion", "product", "requestId", "signerId",
            "certifierId"
            } or request.get("schemaVersion") != 1
            or request.get("signerId") != mapping["signerId"]
            or request.get("certifierId") != mapping["certifierId"]
            or IDENTIFIER.fullmatch(str(request.get("requestId", "")))
                is None):
        raise ValueError("signer capability request is malformed")
    return {
        "schemaVersion": 1, "product": CAPABILITY_MANIFEST_PRODUCT,
        "requestId": request["requestId"], "signerId": mapping["signerId"],
        "certifierId": mapping["certifierId"],
        "implementationId": "pdr-local-ed25519-certifier-signer-v1",
        "protocolMajor": 1, "protocolMinor": 0,
        "capabilities": CAPABILITIES,
        "keyIds": sorted(item["keyId"] for item in mapping["keys"]),
    }


def sign(request: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "schemaVersion", "product", "requestId", "signerId", "certifierId",
        "operation", "purpose", "keyId", "algorithm", "payloadBase64",
        "payloadSha256",
    }
    if (set(request) != fields or request.get("schemaVersion") != 1
            or request.get("product") != REQUEST_PRODUCT
            or request.get("signerId") != mapping["signerId"]
            or request.get("certifierId") != mapping["certifierId"]
            or request.get("operation") != "sign"
            or request.get("purpose") != "adapter-conformance-attestation"
            or request.get("algorithm") != "Ed25519"
            or any(IDENTIFIER.fullmatch(str(request.get(name, ""))) is None
                   for name in ("requestId", "keyId"))):
        raise ValueError("signer request is malformed")
    try:
        payload = base64.b64decode(request["payloadBase64"], validate=True)
    except (TypeError, ValueError) as error:
        raise ValueError("signer payload encoding is invalid") from error
    if (not 1 <= len(payload) <= 64 * 1024
            or hashlib.sha256(payload).hexdigest()
                != request.get("payloadSha256")):
        raise ValueError("signer payload identity changed")
    selected = next((item for item in mapping["keys"]
                     if item["keyId"] == request["keyId"]), None)
    fault = os.environ.get("PDR_CERTIFIER_SIGNER_FAULT")
    if selected is None or fault == "reject":
        return response(request, False, None, "key-unavailable")
    key_value = os.environ.get(selected["privateKeyEnvironment"])
    if not key_value:
        return response(request, False, None, "key-unavailable")
    key_path = Path(key_value)
    if (not key_path.is_absolute() or key_path.is_symlink()
            or not key_path.is_file()):
        return response(request, False, None, "key-unavailable")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import \
        load_pem_private_key
    private = load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        return response(request, False, None, "signing-failed")
    signature = private.sign(payload)
    if fault == "corrupt-signature":
        signature = bytes([signature[0] ^ 1]) + signature[1:]
    key_id = "wrong-key" if fault == "wrong-key-id" else request["keyId"]
    result = response(request, True, signature, None)
    result["keyId"] = key_id
    return result


def response(request: dict[str, Any], passed: bool,
             signature: bytes | None, error_code: str | None) \
        -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": RESPONSE_PRODUCT,
        "requestId": request["requestId"], "signerId": request["signerId"],
        "certifierId": request["certifierId"],
        "operation": request["operation"], "purpose": request["purpose"],
        "keyId": request["keyId"], "algorithm": request["algorithm"],
        "passed": passed,
        "signatureBase64": base64.b64encode(signature).decode("ascii")
            if signature is not None else None,
        "errorCode": error_code,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--mapping", required=True)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        mapping = load_mapping(args.mapping)
        request = read_request()
        document = capability(request, mapping) \
            if request.get("product") == CAPABILITY_REQUEST_PRODUCT \
            else sign(request, mapping)
        sys.stdout.write(json.dumps(
            document, sort_keys=True, separators=(",", ":")
        ))
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_CERTIFIER_SIGNER_SAMPLE_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
