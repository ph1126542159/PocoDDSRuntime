#!/usr/bin/env python3
"""Pinned external-command content-addressed artifact store client."""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import team_contract_package as package_tool
import team_contract_registry as registry_tool
import team_contract_adapter_runtime as adapter_runtime


CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractArtifactStoreConfig"
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractArtifactStoreRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractArtifactStoreResponse"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractArtifactStoreCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractArtifactStoreCapabilityManifest"
OPERATIONS = {"put", "get"}
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MEDIA_TYPE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}/"
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}$"
)


def _regular_pinned_file(path_value: str, expected_sha: str, label: str) -> Path:
    return adapter_runtime.regular_pinned_file(
        path_value, expected_sha, label
    )


def validate_config(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "storeId", "kind", "namespaceIds",
        "protocolMajor", "minimumProtocolMinor", "requiredCapabilities",
        "executable", "executableSha256", "arguments", "artifactPins",
        "environmentVariables", "timeoutSeconds", "maxResponseBytes",
        "maxArtifactBytes",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CONFIG_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("storeId", "")))
            or document.get("kind") != "external-command"
            or not isinstance(document.get("namespaceIds"), list)
            or not document["namespaceIds"]
            or len(document["namespaceIds"]) > 128
            or document["namespaceIds"]
                != sorted(set(document["namespaceIds"]))
            or any(not package_tool.IDENTIFIER.fullmatch(str(item))
                   for item in document["namespaceIds"])
            or type(document.get("protocolMajor")) is not int
            or not 1 <= document["protocolMajor"] <= 65535
            or type(document.get("minimumProtocolMinor")) is not int
            or not 0 <= document["minimumProtocolMinor"] <= 65535
            or not isinstance(document.get("requiredCapabilities"), list)
            or not document["requiredCapabilities"]
            or document["requiredCapabilities"]
                != sorted(set(document["requiredCapabilities"]))
            or len(document["requiredCapabilities"]) > 32
            or any(not isinstance(item, str)
                   or CAPABILITY_ID.fullmatch(item) is None
                   for item in document["requiredCapabilities"])
            or not isinstance(document.get("executable"), str)
            or not package_tool.SHA256.fullmatch(
                str(document.get("executableSha256", "")))
            or not isinstance(document.get("arguments"), list)
            or len(document["arguments"]) > 32
            or any(not isinstance(item, str) or not item
                   or len(item) > 1024 or "\x00" in item
                   for item in document["arguments"])
            or not isinstance(document.get("artifactPins"), list)
            or len(document["artifactPins"]) > 32
            or not isinstance(document.get("environmentVariables"), list)
            or len(document["environmentVariables"]) > 32
            or document["environmentVariables"]
                != sorted(set(document["environmentVariables"]))
            or any(ENVIRONMENT_NAME.fullmatch(str(item)) is None
                   for item in document["environmentVariables"])
            or type(document.get("timeoutSeconds")) is not int
            or not 1 <= document["timeoutSeconds"] <= 60
            or type(document.get("maxResponseBytes")) is not int
            or not 4096 <= document["maxResponseBytes"] <= 64 * 1024 * 1024
            or type(document.get("maxArtifactBytes")) is not int
            or not 1 <= document["maxArtifactBytes"] <= 16 * 1024 * 1024
            or document["maxResponseBytes"]
                < ((document["maxArtifactBytes"] + 2) // 3) * 4 + 4096):
        raise ValueError("artifact store configuration is malformed")
    seen: set[str] = set()
    for item in document["artifactPins"]:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                or not isinstance(item.get("path"), str)
                or item["path"] in seen
                or not package_tool.SHA256.fullmatch(
                    str(item.get("sha256", "")))):
            raise ValueError("artifact store artifact pin is malformed")
        seen.add(item["path"])


def load_config(path_value: str | Path, expected_sha: str,
                namespace_id: str) -> tuple[dict[str, Any], Path, str]:
    path = package_tool.resolved_path(path_value, "artifact store config")
    content = path.read_bytes()
    digest = package_tool.sha256_bytes(content)
    expected = str(expected_sha).lower()
    if (not package_tool.SHA256.fullmatch(expected) or digest != expected):
        raise ValueError("artifact store configuration identity is not pinned")
    document = json.loads(content)
    validate_config(document)
    if namespace_id not in document["namespaceIds"]:
        raise ValueError("artifact store namespace is not authorized")
    _regular_pinned_file(
        document["executable"], document["executableSha256"],
        "artifact store executable",
    )
    for artifact in document["artifactPins"]:
        _regular_pinned_file(
            artifact["path"], artifact["sha256"], "artifact store artifact"
        )
    return document, path, digest


def validate_reference(document: Any, *, store_id: str | None = None,
                       namespace_id: str | None = None) -> dict[str, Any]:
    fields = {
        "kind", "storeId", "namespaceId", "sha256", "sizeBytes",
        "mediaType",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("kind") != "content-addressed"
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("storeId", "")))
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("namespaceId", "")))
            or not package_tool.SHA256.fullmatch(
                str(document.get("sha256", "")))
            or type(document.get("sizeBytes")) is not int
            or document["sizeBytes"] < 1
            or not isinstance(document.get("mediaType"), str)
            or MEDIA_TYPE.fullmatch(document["mediaType"]) is None
            or (store_id is not None and document["storeId"] != store_id)
            or (namespace_id is not None
                and document["namespaceId"] != namespace_id)):
        raise ValueError("artifact reference is malformed or out of scope")
    return document


def _request(store_id: str, namespace_id: str, operation: str,
             digest: str, content: bytes | None, media_type: str) \
        -> dict[str, Any]:
    request = {
        "schemaVersion": 1, "product": REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "storeId": store_id,
        "namespaceId": namespace_id, "operation": operation,
        "sha256": digest, "sizeBytes": len(content) if content else None,
        "mediaType": media_type,
        "contentBase64": base64.b64encode(content).decode("ascii")
            if content is not None else None,
    }
    validate_request(request)
    return request


def validate_request(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "storeId", "namespaceId",
        "operation", "sha256", "sizeBytes", "mediaType", "contentBase64",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != REQUEST_PRODUCT
            or any(not package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, "")))
                for name in ("requestId", "storeId", "namespaceId"))
            or document.get("operation") not in OPERATIONS
            or not package_tool.SHA256.fullmatch(
                str(document.get("sha256", "")))
            or not isinstance(document.get("mediaType"), str)
            or MEDIA_TYPE.fullmatch(document["mediaType"]) is None):
        raise ValueError("artifact store request is malformed")
    if document["operation"] == "put":
        if (type(document.get("sizeBytes")) is not int
                or document["sizeBytes"] < 1
                or not isinstance(document.get("contentBase64"), str)):
            raise ValueError("artifact store put request is malformed")
    elif document["sizeBytes"] is not None \
            or document["contentBase64"] is not None:
        raise ValueError("artifact store get request is malformed")


def _capability_request(store_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": CAPABILITY_REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "storeId": store_id,
    }


def validate_capability_manifest(document: Any,
                                 request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "storeId",
        "implementationId", "protocolMajor", "protocolMinor", "capabilities",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CAPABILITY_MANIFEST_PRODUCT
            or document.get("requestId") != request["requestId"]
            or document.get("storeId") != request["storeId"]
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("implementationId", "")))
            or type(document.get("protocolMajor")) is not int
            or type(document.get("protocolMinor")) is not int
            or not isinstance(document.get("capabilities"), list)
            or not document["capabilities"]
            or document["capabilities"]
                != sorted(set(document["capabilities"]))
            or any(not isinstance(item, str)
                   or CAPABILITY_ID.fullmatch(item) is None
                   for item in document["capabilities"])):
        raise ValueError("artifact store capability manifest is malformed")


def validate_response(document: Any, request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "storeId", "operation",
        "passed", "found", "stored", "sha256", "sizeBytes", "mediaType",
        "contentBase64", "error",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != RESPONSE_PRODUCT
            or document.get("requestId") != request["requestId"]
            or document.get("storeId") != request["storeId"]
            or document.get("operation") != request["operation"]
            or type(document.get("passed")) is not bool
            or type(document.get("found")) is not bool
            or (document.get("stored") is not None
                and type(document["stored"]) is not bool)
            or (document.get("error") is not None
                and (not isinstance(document["error"], str)
                     or not 1 <= len(document["error"]) <= 1024))):
        raise ValueError("artifact store response is malformed or mismatched")
    if not document["passed"]:
        if document["error"] is None:
            raise ValueError("artifact store failure lacks an error")
        return
    if document["error"] is not None:
        raise ValueError("artifact store success contains an error")
    if document["found"]:
        if (document.get("sha256") != request["sha256"]
                or type(document.get("sizeBytes")) is not int
                or document["sizeBytes"] < 1
                or document.get("mediaType") != request["mediaType"]):
            raise ValueError("artifact store response identity changed")
    elif any(document.get(name) is not None for name in (
            "sha256", "sizeBytes", "mediaType", "contentBase64")):
        raise ValueError("artifact store missing response contains content")
    if request["operation"] == "put":
        if (document["stored"] is not True
                or not document["found"]
                or document["contentBase64"] is not None):
            raise ValueError("artifact store put response is malformed")
    elif (document["stored"] is not None
          or (document["found"]
              and not isinstance(document["contentBase64"], str))):
        raise ValueError("artifact store get response is malformed")


class ExternalCommandArtifactStore:
    def __init__(self, config_path: str | Path,
                 expected_config_sha256: str, namespace_id: str) -> None:
        self.config, self.config_path, self.config_sha256 = load_config(
            config_path, expected_config_sha256, namespace_id
        )
        self.namespace_id = namespace_id
        request = _capability_request(self.store_id)
        manifest = self._invoke(request, configured_environment=False)
        validate_capability_manifest(manifest, request)
        adapter_runtime.enforce_capability_policy(
            self.config, manifest, "artifact store"
        )
        self.capability_manifest = manifest
        self.capability_manifest_sha256 = adapter_runtime.capability_digest(
            manifest, "storeId"
        )

    @property
    def store_id(self) -> str:
        return str(self.config["storeId"])

    def descriptor(self) -> dict[str, Any]:
        return {
            "kind": "external-command", "storeId": self.store_id,
            "configPath": str(self.config_path),
            "configSha256": self.config_sha256,
            "capabilityManifestSha256": self.capability_manifest_sha256,
        }

    def _invoke(self, request: dict[str, Any], *,
                configured_environment: bool = True) -> dict[str, Any]:
        config, path, digest = load_config(
            self.config_path, self.config_sha256, self.namespace_id
        )
        if config != self.config or path != self.config_path \
                or digest != self.config_sha256:
            raise ValueError("artifact store configuration changed")
        environment = adapter_runtime.isolated_environment(
            config["environmentVariables"],
            require_required=configured_environment,
            label="artifact store",
        )
        command = [str(Path(config["executable"]).resolve()), *config["arguments"]]
        return adapter_runtime.invoke_json(
            command, request, environment=environment,
            timeout_seconds=config["timeoutSeconds"],
            max_response_bytes=config["maxResponseBytes"],
            label="artifact store", expose_stderr=False,
        )

    def _execute(self, request: dict[str, Any]) -> dict[str, Any]:
        response = self._invoke(request)
        validate_response(response, request)
        if not response["passed"]:
            raise RuntimeError(f"artifact store rejected request: {response['error']}")
        return response

    def put(self, content: bytes,
            media_type: str = "application/octet-stream") -> dict[str, Any]:
        if (not content or len(content) > self.config["maxArtifactBytes"]
                or MEDIA_TYPE.fullmatch(media_type) is None):
            raise ValueError("artifact content or media type is outside policy")
        digest = package_tool.sha256_bytes(content)
        response = self._execute(_request(
            self.store_id, self.namespace_id, "put", digest, content, media_type
        ))
        if response["sizeBytes"] != len(content):
            raise ValueError("artifact store put size changed")
        reference = {
            "kind": "content-addressed", "storeId": self.store_id,
            "namespaceId": self.namespace_id, "sha256": digest,
            "sizeBytes": len(content), "mediaType": media_type,
        }
        readback = self.get(reference)
        if readback != content:
            raise RuntimeError("artifact store read-after-write changed content")
        return reference

    def get(self, reference: dict[str, Any]) -> bytes:
        validate_reference(
            reference, store_id=self.store_id, namespace_id=self.namespace_id
        )
        response = self._execute(_request(
            self.store_id, self.namespace_id, "get", reference["sha256"],
            None, reference["mediaType"],
        ))
        if not response["found"]:
            raise ValueError("artifact store content is unavailable")
        try:
            content = base64.b64decode(response["contentBase64"], validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("artifact store content encoding is malformed") from exc
        if (len(content) != reference["sizeBytes"]
                or package_tool.sha256_bytes(content) != reference["sha256"]
                or len(content) > self.config["maxArtifactBytes"]):
            raise ValueError("artifact store content identity changed")
        return content


def put_command(args: argparse.Namespace) -> int:
    try:
        path = package_tool.resolved_path(args.input, "artifact input")
        content = path.read_bytes()
        store = ExternalCommandArtifactStore(
            args.config, args.expected_config_sha256, args.namespace_id
        )
        reference = store.put(content, args.media_type)
        output = Path(args.reference_output)
        if not output.is_absolute():
            raise ValueError("artifact reference output must be absolute")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(package_tool.json_bytes(reference))
        print(
            "PDR_ARTIFACT_STORE_PUT_PASS "
            f"store={store.store_id} namespace={args.namespace_id} "
            f"sha256={reference['sha256']} reference={output}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ARTIFACT_STORE_PUT_ERROR: {error}", file=sys.stderr)
        return 2


def get_command(args: argparse.Namespace) -> int:
    try:
        reference_path = package_tool.resolved_path(
            args.reference, "artifact reference"
        )
        reference = json.loads(reference_path.read_bytes())
        validate_reference(reference, namespace_id=args.namespace_id)
        store = ExternalCommandArtifactStore(
            args.config, args.expected_config_sha256, args.namespace_id
        )
        content = store.get(reference)
        output = Path(args.output)
        if not output.is_absolute():
            raise ValueError("artifact output must be absolute")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(content)
        print(
            "PDR_ARTIFACT_STORE_GET_PASS "
            f"store={store.store_id} namespace={args.namespace_id} "
            f"sha256={reference['sha256']} output={output}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ARTIFACT_STORE_GET_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name, handler in (("put", put_command), ("get", get_command)):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True)
        command.add_argument("--expected-config-sha256", required=True)
        command.add_argument("--namespace-id", required=True)
        command.set_defaults(handler=handler)
    put = commands.choices["put"]
    put.add_argument("--input", required=True)
    put.add_argument("--media-type", default="application/octet-stream")
    put.add_argument("--reference-output", required=True)
    get = commands.choices["get"]
    get.add_argument("--reference", required=True)
    get.add_argument("--output", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
