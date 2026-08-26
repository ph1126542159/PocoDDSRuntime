#!/usr/bin/env python3
"""Pinned external-command backend for linearizable Registry leader authority state."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import team_contract_package as package_tool
import team_contract_registry as registry_tool


CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig"
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendResponse"
ZERO_SHA256 = "0" * 64
OPERATIONS = {"read-current", "read-grant", "compare-and-swap"}
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class BackendCommitUncertainError(RuntimeError):
    """The CAS request may have committed but its final state was not proven."""


def _regular_pinned_file(path_value: str, expected_sha: str, label: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError(f"{label} path must be absolute")
    resolved = path.resolve()
    if (registry_tool.linklike(path) or registry_tool.linklike(resolved)
            or not resolved.is_file()):
        raise ValueError(f"{label} must be a regular non-link file")
    if package_tool.sha256_file(resolved) != expected_sha:
        raise ValueError(f"{label} digest changed")
    return resolved


def validate_config(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "backendId", "kind", "authorityIds",
        "registryIds", "executable", "executableSha256", "arguments",
        "artifactPins", "environmentVariables", "timeoutSeconds",
        "maxResponseBytes",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CONFIG_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("backendId", "")))
            or document.get("kind") != "external-command"
            or any(not isinstance(document.get(name), list)
                   or not document[name] or len(document[name]) > 128
                   or len(document[name]) != len(set(document[name]))
                   or any(not package_tool.IDENTIFIER.fullmatch(str(item))
                          for item in document[name])
                   for name in ("authorityIds", "registryIds"))
            or not isinstance(document.get("executable"), str)
            or not package_tool.SHA256.fullmatch(
                str(document.get("executableSha256", "")))
            or not isinstance(document.get("arguments"), list)
            or len(document["arguments"]) > 32
            or any(not isinstance(item, str) or not item or len(item) > 1024
                   or "\x00" in item for item in document["arguments"])
            or not isinstance(document.get("artifactPins"), list)
            or len(document["artifactPins"]) > 32
            or not isinstance(document.get("environmentVariables"), list)
            or len(document["environmentVariables"]) > 32
            or len(document["environmentVariables"])
                != len(set(document["environmentVariables"]))
            or any(not ENVIRONMENT_NAME.fullmatch(str(item))
                   for item in document["environmentVariables"])
            or type(document.get("timeoutSeconds")) is not int
            or not 1 <= document["timeoutSeconds"] <= 30
            or type(document.get("maxResponseBytes")) is not int
            or not 1024 <= document["maxResponseBytes"] <= 1024 * 1024):
        raise ValueError("Registry leader backend configuration is malformed")
    seen: set[str] = set()
    for item in document["artifactPins"]:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                or not isinstance(item.get("path"), str)
                or item["path"] in seen
                or not package_tool.SHA256.fullmatch(
                    str(item.get("sha256", "")))):
            raise ValueError("Registry leader backend artifact pin is malformed")
        seen.add(item["path"])


def load_config(path_value: str | Path, expected_sha: str,
                authority_id: str, registry_id: str) \
        -> tuple[dict[str, Any], Path, str]:
    path = package_tool.resolved_path(path_value, "Registry leader backend config")
    content = path.read_bytes()
    actual = package_tool.sha256_bytes(content)
    expected = str(expected_sha).lower()
    if (not package_tool.SHA256.fullmatch(expected) or actual != expected):
        raise ValueError("Registry leader backend configuration identity is not pinned")
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Registry leader backend configuration is invalid JSON") from error
    validate_config(document)
    if (authority_id not in document["authorityIds"]
            or registry_id not in document["registryIds"]):
        raise ValueError("Registry leader backend scope is not authorized")
    _regular_pinned_file(
        document["executable"], document["executableSha256"],
        "Registry leader backend executable",
    )
    for artifact in document["artifactPins"]:
        _regular_pinned_file(
            artifact["path"], artifact["sha256"],
            "Registry leader backend artifact",
        )
    return document, path, actual


def _request(operation: str, backend_id: str, authority_id: str,
             registry_id: str, *, token: int | None = None,
             grant_sha256: str | None = None,
             expected_token: int | None = None,
             expected_sha256: str | None = None,
             grant_content: bytes | None = None) -> dict[str, Any]:
    document = {
        "schemaVersion": 1, "product": REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "backendId": backend_id,
        "authorityId": authority_id, "registryId": registry_id,
        "operation": operation, "fencingToken": token,
        "grantSha256": grant_sha256,
        "expectedCurrentToken": expected_token,
        "expectedCurrentGrantSha256": expected_sha256,
        "grantBase64": base64.b64encode(grant_content).decode("ascii")
            if grant_content is not None else None,
    }
    validate_request(document)
    return document


def validate_request(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "backendId", "authorityId",
        "registryId", "operation", "fencingToken", "grantSha256",
        "expectedCurrentToken", "expectedCurrentGrantSha256", "grantBase64",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != REQUEST_PRODUCT
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(name, "")))
                   for name in ("requestId", "backendId", "authorityId", "registryId"))
            or document.get("operation") not in OPERATIONS):
        raise ValueError("Registry leader backend request is malformed")
    operation = document["operation"]
    if operation == "read-current":
        if any(document[name] is not None for name in (
                "fencingToken", "grantSha256", "expectedCurrentToken",
                "expectedCurrentGrantSha256", "grantBase64")):
            raise ValueError("Registry leader backend current request is malformed")
    elif operation == "read-grant":
        if (type(document["fencingToken"]) is not int
                or document["fencingToken"] < 1
                or not package_tool.SHA256.fullmatch(
                    str(document["grantSha256"] or ""))
                or any(document[name] is not None for name in (
                    "expectedCurrentToken", "expectedCurrentGrantSha256",
                    "grantBase64"))):
            raise ValueError("Registry leader backend history request is malformed")
    else:
        if (type(document["fencingToken"]) is not int
                or document["fencingToken"] < 1
                or not package_tool.SHA256.fullmatch(
                    str(document["grantSha256"] or ""))
                or type(document["expectedCurrentToken"]) is not int
                or document["expectedCurrentToken"] < 0
                or not package_tool.SHA256.fullmatch(
                    str(document["expectedCurrentGrantSha256"] or ""))
                or not isinstance(document["grantBase64"], str)):
            raise ValueError("Registry leader backend CAS request is malformed")


def validate_response(document: Any, request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "backendId", "operation",
        "passed", "found", "committed", "fencingToken", "grantSha256",
        "grantBase64", "error",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != RESPONSE_PRODUCT
            or document.get("requestId") != request["requestId"]
            or document.get("backendId") != request["backendId"]
            or document.get("operation") != request["operation"]
            or type(document.get("passed")) is not bool
            or type(document.get("found")) is not bool
            or (document.get("committed") is not None
                and type(document["committed"]) is not bool)
            or (document.get("error") is not None
                and (not isinstance(document["error"], str)
                     or not 1 <= len(document["error"]) <= 1024))):
        raise ValueError("Registry leader backend response is malformed or mismatched")
    if not document["passed"]:
        if document["error"] is None:
            raise ValueError("Registry leader backend failure lacks an error")
        return
    if document["error"] is not None:
        raise ValueError("Registry leader backend success contains an error")
    if request["operation"] == "compare-and-swap":
        if (type(document["committed"]) is not bool
                or document["grantBase64"] is not None
                or (document["committed"] and not document["found"])):
            raise ValueError("Registry leader backend CAS response is malformed")
        if document["found"]:
            if (type(document["fencingToken"]) is not int
                    or document["fencingToken"] < 1
                    or not package_tool.SHA256.fullmatch(
                        str(document["grantSha256"] or ""))):
                raise ValueError(
                    "Registry leader backend CAS response is malformed"
                )
        elif (document["fencingToken"] is not None
              or document["grantSha256"] is not None):
            raise ValueError("Registry leader backend CAS response is malformed")
    elif document["committed"] is not None:
        raise ValueError("Registry leader backend read response contains CAS state")
    if request["operation"] != "compare-and-swap" and document["found"]:
        if (type(document["fencingToken"]) is not int
                or document["fencingToken"] < 1
                or not package_tool.SHA256.fullmatch(
                    str(document["grantSha256"] or ""))
                or not isinstance(document["grantBase64"], str)):
            raise ValueError("Registry leader backend grant response is malformed")
    elif request["operation"] != "compare-and-swap" and any(
            document[name] is not None
            for name in ("fencingToken", "grantSha256", "grantBase64")):
        raise ValueError("Registry leader backend missing response contains grant state")


class ExternalCommandBackend:
    def __init__(self, config_path: str | Path, expected_config_sha256: str,
                 authority_id: str, registry_id: str) -> None:
        self.config, self.config_path, self.config_sha256 = load_config(
            config_path, expected_config_sha256, authority_id, registry_id
        )
        self.authority_id = authority_id
        self.registry_id = registry_id

    @property
    def backend_id(self) -> str:
        return str(self.config["backendId"])

    def descriptor(self) -> dict[str, Any]:
        return {
            "kind": "external-command", "backendId": self.backend_id,
            "configPath": str(self.config_path),
            "configSha256": self.config_sha256,
        }

    def _invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        # Revalidate every invocation so an executable, adapter, or config cannot
        # drift after activation and silently weaken the fencing boundary.
        config, path, digest = load_config(
            self.config_path, self.config_sha256,
            self.authority_id, self.registry_id,
        )
        if config != self.config or path != self.config_path or digest != self.config_sha256:
            raise ValueError("Registry leader backend configuration changed")
        environment: dict[str, str] = {}
        for name in ("SystemRoot", "WINDIR"):
            if name in os.environ:
                environment[name] = os.environ[name]
        for name in config["environmentVariables"]:
            if name not in os.environ:
                raise ValueError(
                    f"Registry leader backend environment is unset: {name}"
                )
            environment[name] = os.environ[name]
        command = [str(Path(config["executable"]).resolve()), *config["arguments"]]
        with tempfile.TemporaryFile() as stdout_file, \
                tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=stdout_file,
                stderr=stderr_file, env=environment,
            )
            try:
                if process.stdin is None:
                    raise RuntimeError("Registry leader backend stdin is unavailable")
                try:
                    process.stdin.write(package_tool.json_bytes(request))
                    process.stdin.flush()
                except BrokenPipeError:
                    pass
                finally:
                    process.stdin.close()
                deadline = time.monotonic() + config["timeoutSeconds"]
                while process.poll() is None:
                    if os.fstat(stdout_file.fileno()).st_size \
                            > config["maxResponseBytes"]:
                        process.kill()
                        process.wait()
                        raise ValueError(
                            "Registry leader backend response size is outside policy"
                        )
                    if time.monotonic() >= deadline:
                        process.kill()
                        process.wait()
                        raise RuntimeError("Registry leader backend timed out")
                    time.sleep(0.01)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            response_size = os.fstat(stdout_file.fileno()).st_size
            if not 1 <= response_size <= config["maxResponseBytes"]:
                raise ValueError(
                    "Registry leader backend response size is outside policy"
                )
            stdout_file.seek(0)
            response_bytes = stdout_file.read(config["maxResponseBytes"] + 1)
            stderr_file.seek(0)
            stderr_bytes = stderr_file.read(1024)
            return_code = process.returncode
        if return_code != 0:
            detail = stderr_bytes.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                "Registry leader backend process failed"
                + (f": {detail}" if detail else "")
            )
        try:
            response = json.loads(response_bytes)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Registry leader backend response is invalid JSON") from error
        validate_response(response, request)
        if not response["passed"]:
            raise RuntimeError(f"Registry leader backend rejected request: {response['error']}")
        return response

    @staticmethod
    def _decode(response: dict[str, Any]) -> tuple[dict[str, Any], bytes, str]:
        try:
            content = base64.b64decode(response["grantBase64"], validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("Registry leader backend grant encoding is invalid") from error
        digest = package_tool.sha256_bytes(content)
        if digest != response["grantSha256"]:
            raise ValueError("Registry leader backend grant digest changed")
        try:
            document = json.loads(content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Registry leader backend grant is invalid JSON") from error
        if not isinstance(document, dict):
            raise ValueError("Registry leader backend grant must be a JSON object")
        if document.get("fencingToken") != response["fencingToken"]:
            raise ValueError("Registry leader backend grant token changed")
        return document, content, digest

    def current(self) -> tuple[dict[str, Any], bytes, str] | None:
        response = self._invoke(_request(
            "read-current", self.backend_id, self.authority_id, self.registry_id
        ))
        return self._decode(response) if response["found"] else None

    def grant(self, token: int, digest: str) -> tuple[dict[str, Any], bytes, str]:
        response = self._invoke(_request(
            "read-grant", self.backend_id, self.authority_id, self.registry_id,
            token=token, grant_sha256=digest,
        ))
        if not response["found"]:
            raise ValueError("Registry leader backend grant history is incomplete")
        loaded = self._decode(response)
        if loaded[2] != digest or loaded[0].get("fencingToken") != token:
            raise ValueError("Registry leader backend history identity changed")
        return loaded

    def compare_and_swap(self, expected_token: int, expected_sha256: str,
                         grant: dict[str, Any], content: bytes, digest: str) -> None:
        try:
            response = self._invoke(_request(
                "compare-and-swap", self.backend_id, self.authority_id,
                self.registry_id, token=grant["fencingToken"], grant_sha256=digest,
                expected_token=expected_token, expected_sha256=expected_sha256,
                grant_content=content,
            ))
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            raise BackendCommitUncertainError(
                f"Registry leader backend CAS outcome is uncertain: {error}"
            ) from error
        if not response["committed"]:
            raise ValueError(
                "Registry current leader grant changed before backend CAS"
            )
        if (response["fencingToken"] != grant["fencingToken"]
                or response["grantSha256"] != digest):
            raise BackendCommitUncertainError(
                "Registry leader backend reported a different committed identity"
            )
        try:
            current = self.current()
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            raise BackendCommitUncertainError(
                f"Registry leader backend CAS committed but read-back failed: {error}"
            ) from error
        if current is None or current[1] != content or current[2] != digest:
            raise BackendCommitUncertainError(
                "Registry leader backend CAS committed but read-back changed"
            )
