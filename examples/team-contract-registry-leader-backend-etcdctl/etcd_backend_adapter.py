#!/usr/bin/env python3
"""PDR Registry leader backend adapter implemented with pinned etcdctl v3."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit


CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderEtcdAdapterConfig"
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendResponse"
ZERO_SHA256 = "0" * 64
MAX_REQUEST_BYTES = 2 * 1024 * 1024
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
VERSION = re.compile(r"^3\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
REQUEST_FIELDS = {
    "schemaVersion", "product", "requestId", "backendId", "authorityId",
    "registryId", "operation", "fencingToken", "grantSha256",
    "expectedCurrentToken", "expectedCurrentGrantSha256", "grantBase64",
}
CONFIG_FIELDS = {
    "schemaVersion", "product", "adapterId", "etcdctl", "etcdctlSha256",
    "etcdctlVersion", "etcdctlArguments", "etcdctlArtifactPins",
    "etcdctlEnvironmentVariables", "endpoints", "keyPrefix",
    "caCertificate", "caCertificateSha256", "clientCertificate",
    "clientCertificateSha256", "clientKey", "clientKeySha256",
    "dialTimeoutSeconds", "commandTimeoutSeconds", "maxResponseBytes",
}


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def regular_pinned_file(value: str, expected_sha: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    resolved = path.resolve()
    if (path.is_symlink() or resolved.is_symlink() or not resolved.is_file()
            or not SHA256.fullmatch(str(expected_sha))
            or sha256(resolved.read_bytes()) != expected_sha):
        raise ValueError(f"{label} is missing, linked, or changed")
    return resolved


def valid_endpoint(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 512:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and parsed.port is not None and parsed.username is None
                and parsed.password is None and not parsed.path
                and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def valid_key_prefix(value: Any) -> bool:
    return (isinstance(value, str)
            and re.fullmatch(r"/[A-Za-z0-9._/-]{1,255}", value) is not None
            and not value.endswith("/") and "//" not in value
            and all(item not in {".", ".."} for item in value.split("/")))


def load_config(path_value: str, expected_sha: str) -> tuple[dict[str, Any], Path]:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("etcd adapter config path must be absolute")
    resolved = path.resolve()
    if path.is_symlink() or resolved.is_symlink() or not resolved.is_file():
        raise ValueError("etcd adapter config must be a regular non-link file")
    content = resolved.read_bytes()
    if not SHA256.fullmatch(str(expected_sha)) or sha256(content) != expected_sha:
        raise ValueError("etcd adapter config identity changed")
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("etcd adapter config is invalid JSON") from error
    if (not isinstance(document, dict) or set(document) != CONFIG_FIELDS
            or document.get("schemaVersion") != 1
            or document.get("product") != CONFIG_PRODUCT
            or not IDENTIFIER.fullmatch(str(document.get("adapterId", "")))
            or any(not isinstance(document.get(name), str)
                   for name in (
                       "etcdctl", "caCertificate", "clientCertificate",
                       "clientKey"))
            or any(not SHA256.fullmatch(str(document.get(name, "")))
                   for name in (
                       "etcdctlSha256", "caCertificateSha256",
                       "clientCertificateSha256", "clientKeySha256"))
            or not VERSION.fullmatch(str(document.get("etcdctlVersion", "")))
            or not isinstance(document.get("etcdctlArguments"), list)
            or len(document["etcdctlArguments"]) > 16
            or any(not isinstance(item, str) or not item or len(item) > 1024
                   or "\x00" in item for item in document["etcdctlArguments"])
            or not isinstance(document.get("etcdctlArtifactPins"), list)
            or len(document["etcdctlArtifactPins"]) > 16
            or not isinstance(document.get("etcdctlEnvironmentVariables"), list)
            or len(document["etcdctlEnvironmentVariables"]) > 16
            or len(document["etcdctlEnvironmentVariables"])
                != len(set(document["etcdctlEnvironmentVariables"]))
            or any(not ENVIRONMENT_NAME.fullmatch(str(item))
                   for item in document["etcdctlEnvironmentVariables"])
            or not isinstance(document.get("endpoints"), list)
            or not 3 <= len(document["endpoints"]) <= 9
            or len(document["endpoints"]) != len(set(document["endpoints"]))
            or any(not valid_endpoint(item) for item in document["endpoints"])
            or not valid_key_prefix(document.get("keyPrefix"))
            or type(document.get("dialTimeoutSeconds")) is not int
            or not 1 <= document["dialTimeoutSeconds"] <= 10
            or type(document.get("commandTimeoutSeconds")) is not int
            or not 1 <= document["commandTimeoutSeconds"] <= 20
            or document["dialTimeoutSeconds"] > document["commandTimeoutSeconds"]
            or type(document.get("maxResponseBytes")) is not int
            or not 4096 <= document["maxResponseBytes"] <= 4 * 1024 * 1024):
        raise ValueError("etcd adapter config is malformed")
    regular_pinned_file(
        document["etcdctl"], document["etcdctlSha256"], "etcdctl executable"
    )
    seen: set[str] = set()
    for item in document["etcdctlArtifactPins"]:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                or not isinstance(item.get("path"), str)
                or item["path"] in seen):
            raise ValueError("etcdctl artifact pin is malformed")
        regular_pinned_file(item["path"], item["sha256"], "etcdctl artifact")
        seen.add(item["path"])
    for path_field, sha_field, label in (
        ("caCertificate", "caCertificateSha256", "etcd CA certificate"),
        ("clientCertificate", "clientCertificateSha256", "etcd client certificate"),
        ("clientKey", "clientKeySha256", "etcd client private key"),
    ):
        regular_pinned_file(document[path_field], document[sha_field], label)
    return document, resolved


def validate_request(document: Any) -> dict[str, Any]:
    if (not isinstance(document, dict) or set(document) != REQUEST_FIELDS
            or document.get("schemaVersion") != 1
            or document.get("product") != REQUEST_PRODUCT
            or any(not IDENTIFIER.fullmatch(str(document.get(name, "")))
                   for name in (
                       "requestId", "backendId", "authorityId", "registryId"
                   ))
            or document.get("operation") not in {
                "read-current", "read-grant", "compare-and-swap"
            }):
        raise ValueError("request envelope is malformed")
    operation = document["operation"]
    if operation == "read-current":
        if any(document[name] is not None for name in (
                "fencingToken", "grantSha256", "expectedCurrentToken",
                "expectedCurrentGrantSha256", "grantBase64")):
            raise ValueError("read-current fields are malformed")
    elif operation == "read-grant":
        if (type(document["fencingToken"]) is not int
                or document["fencingToken"] < 1
                or not SHA256.fullmatch(str(document["grantSha256"] or ""))
                or any(document[name] is not None for name in (
                    "expectedCurrentToken", "expectedCurrentGrantSha256",
                    "grantBase64"))):
            raise ValueError("read-grant fields are malformed")
    elif (type(document["fencingToken"]) is not int
          or document["fencingToken"] < 1
          or not SHA256.fullmatch(str(document["grantSha256"] or ""))
          or type(document["expectedCurrentToken"]) is not int
          or document["expectedCurrentToken"] < 0
          or not SHA256.fullmatch(
              str(document["expectedCurrentGrantSha256"] or ""))
          or not isinstance(document["grantBase64"], str)):
        raise ValueError("compare-and-swap fields are malformed")
    return document


def read_request() -> dict[str, Any]:
    content = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if not content or len(content) > MAX_REQUEST_BYTES:
        raise ValueError("request size is outside policy")
    try:
        return validate_request(json.loads(content))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("request is invalid JSON") from error


class EtcdStore:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def command(self, *arguments: str, stdin: bytes | None = None) -> bytes:
        environment: dict[str, str] = {"ETCDCTL_API": "3"}
        for name in ("SystemRoot", "WINDIR"):
            if name in os.environ:
                environment[name] = os.environ[name]
        for name in self.config["etcdctlEnvironmentVariables"]:
            if name not in os.environ:
                raise ValueError(f"etcdctl environment is unset: {name}")
            environment[name] = os.environ[name]
        command = [
            str(Path(self.config["etcdctl"]).resolve()),
            *self.config["etcdctlArguments"],
            f"--endpoints={','.join(self.config['endpoints'])}",
            f"--cacert={Path(self.config['caCertificate']).resolve()}",
            f"--cert={Path(self.config['clientCertificate']).resolve()}",
            f"--key={Path(self.config['clientKey']).resolve()}",
            f"--dial-timeout={self.config['dialTimeoutSeconds']}s",
            f"--command-timeout={self.config['commandTimeoutSeconds']}s",
            *arguments,
        ]
        with tempfile.TemporaryFile() as stdout_file, \
                tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=stdout_file,
                stderr=stderr_file, env=environment,
            )
            try:
                process.communicate(
                    input=stdin,
                    timeout=self.config["commandTimeoutSeconds"] + 1,
                )
            except subprocess.TimeoutExpired as error:
                process.kill()
                process.wait()
                raise RuntimeError("etcdctl command timed out") from error
            size = os.fstat(stdout_file.fileno()).st_size
            if size > self.config["maxResponseBytes"]:
                raise ValueError("etcdctl response size is outside policy")
            stdout_file.seek(0)
            output = stdout_file.read(self.config["maxResponseBytes"] + 1)
            stderr_file.seek(0)
            stderr = stderr_file.read(1024)
            return_code = process.returncode
        if return_code != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError("etcdctl command failed" + (f": {detail}" if detail else ""))
        return output

    def get(self, key: str) -> tuple[dict[str, Any], bytes, str] | None:
        output = self.command(
            "--write-out=json", "get", key, "--limit=1", "--consistency=l"
        )
        try:
            result = json.loads(output)
            if not isinstance(result, dict):
                raise ValueError("etcd range result is not an object")
            items = result.get("kvs", [])
            if not isinstance(items, list) or len(items) > 1:
                raise ValueError("etcd range returned an invalid item count")
            if not items:
                return None
            item = items[0]
            actual_key = base64.b64decode(item["key"], validate=True).decode("utf-8")
            stored = base64.b64decode(item["value"], validate=True)
            if actual_key != key:
                raise ValueError("etcd range returned a different key")
            content = base64.b64decode(stored, validate=True)
            document = json.loads(content)
        except (KeyError, TypeError, UnicodeError, ValueError,
                json.JSONDecodeError) as error:
            raise ValueError("etcd range response is malformed") from error
        digest = sha256(content)
        if (not isinstance(document, dict)
                or type(document.get("fencingToken")) is not int
                or document["fencingToken"] < 1):
            raise ValueError("etcd grant identity is malformed")
        return document, content, digest

    def transaction(self, comparisons: list[str], operations: list[str]) -> bool:
        content = ("\n".join([*comparisons, "", *operations, "", ""])
                   + "\n").encode("utf-8")
        output = self.command("txn", stdin=content)
        lines = output.decode("utf-8", errors="strict").splitlines()
        result = next((line.strip() for line in lines if line.strip()), "")
        if result not in {"SUCCESS", "FAILURE"}:
            raise ValueError("etcdctl transaction response is malformed")
        return result == "SUCCESS"


def response(request: dict[str, Any], *, found: bool,
             committed: bool | None,
             grant: tuple[dict[str, Any], bytes, str] | None = None,
             passed: bool = True, error: str | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": RESPONSE_PRODUCT,
        "requestId": request["requestId"], "backendId": request["backendId"],
        "operation": request["operation"], "passed": passed, "found": found,
        "committed": committed,
        "fencingToken": grant[0]["fencingToken"] if grant else None,
        "grantSha256": grant[2] if grant else None,
        "grantBase64": base64.b64encode(grant[1]).decode("ascii")
            if grant and request["operation"] != "compare-and-swap" else None,
        "error": error,
    }


def key_scope(config: dict[str, Any], request: dict[str, Any]) -> str:
    return (
        f"{config['keyPrefix']}/authorities/"
        f"{quote(request['authorityId'], safe='')}/registries/"
        f"{quote(request['registryId'], safe='')}"
    )


def quoted(value: str) -> str:
    # Keys are URL-quoted ASCII and values are base64 ASCII, so JSON string
    # quoting is compatible with etcdctl's documented Go %q transaction input.
    return json.dumps(value, ensure_ascii=True)


def compare_and_swap(request: dict[str, Any], store: EtcdStore,
                     scope: str) -> dict[str, Any]:
    current_key = f"{scope}/current"
    current = store.get(current_key)
    actual_token = current[0]["fencingToken"] if current else 0
    actual_sha = current[2] if current else ZERO_SHA256
    if (actual_token, actual_sha) != (
            request["expectedCurrentToken"],
            request["expectedCurrentGrantSha256"]):
        return response(request, found=current is not None, committed=False,
                        grant=current)
    try:
        content = base64.b64decode(request["grantBase64"], validate=True)
        document = json.loads(content)
    except (ValueError, TypeError, UnicodeError,
            json.JSONDecodeError) as error:
        return response(
            request, found=False, committed=None, passed=False,
            error=f"candidate grant is malformed: {error}",
        )
    digest = sha256(content)
    previous = None if actual_token == 0 else actual_sha
    if (not isinstance(document, dict)
            or digest != request["grantSha256"]
            or document.get("fencingToken") != request["fencingToken"]
            or request["fencingToken"] != actual_token + 1
            or document.get("previousGrantSha256") != previous):
        return response(
            request, found=False, committed=None, passed=False,
            error="candidate grant violates token, digest, or history chain",
        )
    stored = base64.b64encode(content).decode("ascii")
    history_key = f"{scope}/grants/{request['fencingToken']:020d}-{digest}"
    comparisons = [f"version({quoted(history_key)}) = \"0\""]
    if current is None:
        comparisons.append(f"version({quoted(current_key)}) = \"0\"")
    else:
        expected_value = base64.b64encode(current[1]).decode("ascii")
        comparisons.append(
            f"value({quoted(current_key)}) = {quoted(expected_value)}"
        )
    operations = [
        f"put {quoted(history_key)} {quoted(stored)}",
        f"put {quoted(current_key)} {quoted(stored)}",
    ]
    if store.transaction(comparisons, operations):
        return response(
            request, found=True, committed=True,
            grant=(document, content, digest),
        )
    after = store.get(current_key)
    if after is not None and after[1] == content and after[2] == digest:
        return response(request, found=True, committed=True, grant=after)
    if after is not None and (after[0]["fencingToken"], after[2]) != (
            request["expectedCurrentToken"],
            request["expectedCurrentGrantSha256"]):
        return response(request, found=True, committed=False, grant=after)
    if after is None and request["expectedCurrentToken"] != 0:
        return response(request, found=False, committed=False)
    return response(
        request, found=False, committed=None, passed=False,
        error="etcd transaction rejected without a new current identity",
    )


def execute(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    store = EtcdStore(config)
    scope = key_scope(config, request)
    operation = request["operation"]
    if operation == "read-current":
        grant = store.get(f"{scope}/current")
        return response(request, found=grant is not None, committed=None,
                        grant=grant)
    if operation == "read-grant":
        key = (
            f"{scope}/grants/{request['fencingToken']:020d}-"
            f"{request['grantSha256']}"
        )
        grant = store.get(key)
        if grant is not None and (grant[0]["fencingToken"], grant[2]) != (
                request["fencingToken"], request["grantSha256"]):
            raise ValueError("etcd history identity changed")
        return response(request, found=grant is not None, committed=None,
                        grant=grant)
    return compare_and_swap(request, store, scope)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", required=True)
    result.add_argument("--expected-config-sha256", required=True)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        config, _ = load_config(args.config, args.expected_config_sha256)
        request = read_request()
        result = execute(request, config)
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(f"PDR_LEADER_ETCD_ADAPTER_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
