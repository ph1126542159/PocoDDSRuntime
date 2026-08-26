#!/usr/bin/env python3
"""Reference file adapter for the PDR Registry leader backend protocol.

This is an SDK example for adapter authors. It provides cross-process CAS and
byte-exact immutable history on one local filesystem; it is not a distributed
consensus backend.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendResponse"
ZERO_SHA256 = "0" * 64
MAX_REQUEST_BYTES = 2 * 1024 * 1024
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUEST_FIELDS = {
    "schemaVersion", "product", "requestId", "backendId", "authorityId",
    "registryId", "operation", "fencingToken", "grantSha256",
    "expectedCurrentToken", "expectedCurrentGrantSha256", "grantBase64",
}


class StoreLock:
    """One-byte advisory lock shared by every adapter process in a scope."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.stream: Any = None

    def __enter__(self) -> "StoreLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        if self.stream.seek(0, os.SEEK_END) == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        if os.name == "nt":
            import msvcrt
            deadline = time.monotonic() + 10
            while True:
                try:
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("timed out acquiring the scope CAS lock")
                    time.sleep(0.01)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_: Any) -> None:
        if os.name == "nt":
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


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


def checked_scope(request: dict[str, Any]) -> Path:
    root_value = os.environ.get("PDR_LEADER_BACKEND_SAMPLE_ROOT", "")
    root_input = Path(root_value)
    if not root_value or not root_input.is_absolute():
        raise ValueError("PDR_LEADER_BACKEND_SAMPLE_ROOT must be absolute")
    root_input.mkdir(parents=True, exist_ok=True)
    root = root_input.resolve()
    if root_input.is_symlink() or not root.is_dir():
        raise ValueError("backend root must be a regular directory")
    authority = root / request["authorityId"]
    scope = authority / request["registryId"]
    authority.mkdir(exist_ok=True)
    scope.mkdir(exist_ok=True)
    if authority.is_symlink() or scope.is_symlink():
        raise ValueError("backend scope must not traverse links")
    return scope


def load_grant(path: Path, expected_token: int | None = None,
               expected_sha: str | None = None) \
        -> tuple[dict[str, Any], bytes, str] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("grant path is not a regular file")
    content = path.read_bytes()
    digest = sha256(content)
    document = json.loads(content)
    if (not isinstance(document, dict)
            or type(document.get("fencingToken")) is not int
            or document["fencingToken"] < 1
            or (expected_token is not None
                and document["fencingToken"] != expected_token)
            or (expected_sha is not None and digest != expected_sha)):
        raise ValueError("persisted grant identity changed")
    return document, content, digest


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


def atomic_replace(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def compare_and_swap(request: dict[str, Any], scope: Path) -> dict[str, Any]:
    current_path = scope / "current.json"
    with StoreLock(scope / ".cas.lock"):
        current = load_grant(current_path)
        actual_token = current[0]["fencingToken"] if current else 0
        actual_sha = current[2] if current else ZERO_SHA256
        if (actual_token, actual_sha) != (
                request["expectedCurrentToken"],
                request["expectedCurrentGrantSha256"]):
            if current is None:
                return response(
                    request, found=False, committed=False,
                )
            return response(request, found=True, committed=False, grant=current)
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
        grants = scope / "grants"
        grants.mkdir(exist_ok=True)
        if grants.is_symlink():
            raise ValueError("grant history directory must not be a link")
        history_path = grants / f"{request['fencingToken']:020d}-{digest}.json"
        try:
            with history_path.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if history_path.is_symlink() or history_path.read_bytes() != content:
                raise ValueError("immutable history identity collision")
        atomic_replace(current_path, content)
        return response(
            request, found=True, committed=True,
            grant=(document, content, digest),
        )


def execute(request: dict[str, Any]) -> dict[str, Any]:
    scope = checked_scope(request)
    operation = request["operation"]
    if operation == "read-current":
        grant = load_grant(scope / "current.json")
        return response(request, found=grant is not None, committed=None,
                        grant=grant)
    if operation == "read-grant":
        path = scope / "grants" / (
            f"{request['fencingToken']:020d}-{request['grantSha256']}.json"
        )
        grant = load_grant(
            path, request["fencingToken"], request["grantSha256"]
        )
        return response(request, found=grant is not None, committed=None,
                        grant=grant)
    return compare_and_swap(request, scope)


def main() -> int:
    try:
        request = read_request()
        result = execute(request)
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_LEADER_BACKEND_SAMPLE_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
