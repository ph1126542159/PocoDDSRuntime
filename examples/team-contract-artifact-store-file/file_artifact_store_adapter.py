#!/usr/bin/env python3
"""Reference immutable file adapter for the PDR Artifact Store SPI."""

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


REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractArtifactStoreRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractArtifactStoreResponse"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractArtifactStoreCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractArtifactStoreCapabilityManifest"
CAPABILITIES = [
    "content-addressed-read", "idempotent-create", "immutable-content",
    "namespace-confinement", "read-after-write",
]
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_REQUEST_BYTES = 24 * 1024 * 1024


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_request() -> dict[str, Any]:
    content = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if not content or len(content) > MAX_REQUEST_BYTES:
        raise ValueError("request size is outside policy")
    document = json.loads(content)
    if (not isinstance(document, dict)
            or document.get("schemaVersion") != 1):
        raise ValueError("request is malformed")
    if document.get("product") == CAPABILITY_REQUEST_PRODUCT:
        if (set(document) != {
                "schemaVersion", "product", "requestId", "storeId"
        } or any(not IDENTIFIER.fullmatch(str(document.get(name, "")))
                 for name in ("requestId", "storeId"))):
            raise ValueError("capability request is malformed")
        return document
    fields = {
        "schemaVersion", "product", "requestId", "storeId", "namespaceId",
        "operation", "sha256", "sizeBytes", "mediaType", "contentBase64",
    }
    if (set(document) != fields or document.get("product") != REQUEST_PRODUCT
            or any(not IDENTIFIER.fullmatch(str(document.get(name, "")))
                   for name in ("requestId", "storeId", "namespaceId"))
            or document.get("operation") not in {"put", "get"}
            or not SHA256.fullmatch(str(document.get("sha256", "")))
            or not isinstance(document.get("mediaType"), str)):
        raise ValueError("artifact request is malformed")
    if document["operation"] == "put":
        if (type(document.get("sizeBytes")) is not int
                or document["sizeBytes"] < 1
                or not isinstance(document.get("contentBase64"), str)):
            raise ValueError("put request is malformed")
    elif document["sizeBytes"] is not None \
            or document["contentBase64"] is not None:
        raise ValueError("get request is malformed")
    return document


def scope(request: dict[str, Any], root_environment: str) -> Path:
    raw = os.environ.get(root_environment, "")
    entered = Path(raw)
    if not raw or not entered.is_absolute():
        raise ValueError(f"{root_environment} must be absolute")
    entered.mkdir(parents=True, exist_ok=True)
    root = entered.resolve()
    if entered.is_symlink() or not root.is_dir():
        raise ValueError("artifact root must be a regular directory")
    result = root / request["storeId"] / request["namespaceId"]
    result.mkdir(parents=True, exist_ok=True)
    for candidate in (result.parent, result):
        if candidate.is_symlink() or not candidate.is_dir():
            raise ValueError("artifact scope must not traverse links")
    return result


def artifact_path(root: Path, sha256: str) -> Path:
    prefix = root / sha256[:2]
    prefix.mkdir(exist_ok=True)
    if prefix.is_symlink() or not prefix.is_dir():
        raise ValueError("artifact prefix must be a regular directory")
    return prefix / f"{sha256}.artifact"


def response(request: dict[str, Any], *, found: bool,
             stored: bool | None, content: bytes | None = None,
             passed: bool = True, error: str | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": RESPONSE_PRODUCT,
        "requestId": request["requestId"], "storeId": request["storeId"],
        "operation": request["operation"], "passed": passed,
        "found": found, "stored": stored,
        "sha256": request["sha256"] if found else None,
        "sizeBytes": len(content) if found and content is not None
            else request.get("sizeBytes") if found else None,
        "mediaType": request["mediaType"] if found else None,
        "contentBase64": base64.b64encode(content).decode("ascii")
            if content is not None and request["operation"] == "get" else None,
        "error": error,
    }


def execute(request: dict[str, Any], root_environment: str) -> dict[str, Any]:
    root = scope(request, root_environment)
    path = artifact_path(root, request["sha256"])
    if request["operation"] == "put":
        try:
            content = base64.b64decode(request["contentBase64"], validate=True)
        except (TypeError, ValueError) as exc:
            return response(
                request, found=False, stored=None, passed=False,
                error=f"artifact encoding is malformed: {exc}",
            )
        if len(content) != request["sizeBytes"] or digest(content) != request["sha256"]:
            return response(
                request, found=False, stored=None, passed=False,
                error="artifact digest or size changed",
            )
        try:
            with path.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if path.is_symlink() or not path.is_file() \
                    or path.read_bytes() != content:
                raise ValueError("immutable artifact identity collision")
        return response(request, found=True, stored=True, content=content)
    if not path.exists():
        return response(request, found=False, stored=None)
    if path.is_symlink() or not path.is_file():
        raise ValueError("artifact path is not a regular file")
    content = path.read_bytes()
    if digest(content) != request["sha256"]:
        raise ValueError("stored artifact identity changed")
    return response(request, found=True, stored=None, content=content)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--root-environment", default="PDR_ARTIFACT_STORE_SAMPLE_ROOT"
    )
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        request = read_request()
        if request["product"] == CAPABILITY_REQUEST_PRODUCT:
            result = {
                "schemaVersion": 1, "product": CAPABILITY_MANIFEST_PRODUCT,
                "requestId": request["requestId"],
                "storeId": request["storeId"],
                "implementationId": "pdr-file-artifact-store-reference-v1",
                "protocolMajor": 1, "protocolMinor": 0,
                "capabilities": CAPABILITIES,
            }
        else:
            result = execute(request, args.root_environment)
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_ARTIFACT_STORE_SAMPLE_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
