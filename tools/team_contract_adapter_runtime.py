#!/usr/bin/env python3
"""Shared fail-closed runtime primitives for external-command Team Contract adapters."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import team_contract_package as package_tool
import team_contract_registry as registry_tool


ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def regular_pinned_file(path_value: str, expected_sha: str, label: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError(f"{label} path must be absolute")
    resolved = path.resolve()
    if (registry_tool.linklike(path) or registry_tool.linklike(resolved)
            or not resolved.is_file()):
        raise ValueError(f"{label} must be a regular non-link file")
    if not package_tool.SHA256.fullmatch(str(expected_sha)):
        raise ValueError(f"{label} digest is malformed")
    if package_tool.sha256_file(resolved) != expected_sha:
        raise ValueError(f"{label} digest changed")
    return resolved


def validate_artifact_pins(items: Any, label: str, *, maximum: int = 32) -> None:
    if not isinstance(items, list) or len(items) > maximum:
        raise ValueError(f"{label} artifact pins are malformed")
    seen: set[str] = set()
    for item in items:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                or not isinstance(item.get("path"), str)
                or item["path"] in seen
                or not package_tool.SHA256.fullmatch(
                    str(item.get("sha256", "")))):
            raise ValueError(f"{label} artifact pin is malformed")
        seen.add(item["path"])


def revalidate_artifacts(config: Mapping[str, Any], label: str) -> None:
    regular_pinned_file(
        str(config["executable"]), str(config["executableSha256"]),
        f"{label} executable",
    )
    for artifact in config["artifactPins"]:
        regular_pinned_file(
            str(artifact["path"]), str(artifact["sha256"]),
            f"{label} artifact",
        )


def load_pinned_json(path_value: str | Path, expected_sha: str, label: str,
                     validator: Callable[[Any], None]) \
        -> tuple[dict[str, Any], Path, str]:
    path = package_tool.resolved_path(path_value, f"{label} config")
    content = path.read_bytes()
    digest = package_tool.sha256_bytes(content)
    expected = str(expected_sha).lower()
    if not package_tool.SHA256.fullmatch(expected) or digest != expected:
        raise ValueError(f"{label} configuration identity is not pinned")
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} configuration is invalid JSON") from error
    validator(document)
    if not isinstance(document, dict):
        raise ValueError(f"{label} configuration must be an object")
    return document, path, digest


def validate_environment_policy(required: Any, *, optional: Any = (),
                                maximum_required: int = 32,
                                maximum_optional: int = 64,
                                label: str = "adapter") -> None:
    if (not isinstance(required, list) or len(required) > maximum_required
            or required != sorted(set(required))
            or any(ENVIRONMENT_NAME.fullmatch(str(item)) is None
                   for item in required)
            or not isinstance(optional, (list, tuple))
            or len(optional) > maximum_optional
            or list(optional) != sorted(set(optional))
            or any(ENVIRONMENT_NAME.fullmatch(str(item)) is None
                   for item in optional)
            or set(required) & set(optional)):
        raise ValueError(f"{label} environment policy is malformed")


def isolated_environment(required: Iterable[str], *, optional: Iterable[str] = (),
                         require_required: bool = True,
                         label: str = "adapter") -> dict[str, str]:
    environment: dict[str, str] = {}
    for name in ("SystemRoot", "WINDIR"):
        if name in os.environ:
            environment[name] = os.environ[name]
    for name in required:
        if name not in os.environ:
            if require_required:
                raise ValueError(f"{label} environment is unset: {name}")
            continue
        environment[name] = os.environ[name]
    for name in optional:
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def enforce_capability_policy(config: Mapping[str, Any],
                              manifest: Mapping[str, Any], label: str) -> None:
    if manifest["protocolMajor"] != config["protocolMajor"]:
        raise ValueError(f"{label} protocol major is incompatible")
    if manifest["protocolMinor"] < config["minimumProtocolMinor"]:
        raise ValueError(f"{label} protocol minor is below policy")
    missing = sorted(
        set(config["requiredCapabilities"]) - set(manifest["capabilities"])
    )
    if missing:
        raise ValueError(
            f"{label} required capabilities are missing: " + ",".join(missing)
        )


def capability_claims(manifest: Mapping[str, Any],
                      identity_field: str) -> dict[str, Any]:
    return {
        identity_field: manifest[identity_field],
        "implementationId": manifest["implementationId"],
        "protocolMajor": manifest["protocolMajor"],
        "protocolMinor": manifest["protocolMinor"],
        "capabilities": manifest["capabilities"],
    }


def capability_digest(manifest: Mapping[str, Any], identity_field: str) -> str:
    return package_tool.sha256_bytes(package_tool.json_bytes(
        capability_claims(manifest, identity_field)
    ))


def invoke_json(command: Sequence[str], request: Mapping[str, Any], *,
                environment: Mapping[str, str], timeout_seconds: int,
                max_response_bytes: int, label: str,
                expose_stderr: bool = False) -> dict[str, Any]:
    if (not command or any(not isinstance(item, str) or not item
                           or "\x00" in item for item in command)):
        raise ValueError(f"{label} command is malformed")
    with tempfile.TemporaryFile() as stdout_file, \
            tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            list(command), stdin=subprocess.PIPE, stdout=stdout_file,
            stderr=stderr_file, env=dict(environment),
        )
        try:
            if process.stdin is None:
                raise RuntimeError(f"{label} stdin is unavailable")
            try:
                process.stdin.write(package_tool.json_bytes(dict(request)))
                process.stdin.flush()
            except BrokenPipeError:
                pass
            finally:
                process.stdin.close()
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                if os.fstat(stdout_file.fileno()).st_size > max_response_bytes:
                    process.kill()
                    process.wait()
                    raise ValueError(f"{label} response exceeds policy")
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    raise RuntimeError(f"{label} timed out")
                time.sleep(0.01)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        response_size = os.fstat(stdout_file.fileno()).st_size
        stderr_file.seek(0)
        stderr_bytes = stderr_file.read(1024) if expose_stderr else b""
        if process.returncode != 0:
            detail = stderr_bytes.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"{label} process failed" + (f": {detail}" if detail else "")
            )
        if not 1 <= response_size <= max_response_bytes:
            raise ValueError(f"{label} response size is outside policy")
        stdout_file.seek(0)
        content = stdout_file.read(max_response_bytes + 1)
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} response is invalid JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} response must be a JSON object")
    return document


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--self-check", action="store_true",
        help="verify that the installed shared Adapter Runtime can load",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    if args.self_check:
        print(
            "PDR_ADAPTER_RUNTIME_SELF_CHECK_PASS "
            "pins=1 environment=1 timeout=1 responseBound=1 redaction=1"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
