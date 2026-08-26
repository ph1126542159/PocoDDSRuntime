#!/usr/bin/env python3
"""Fault-injectable file store implementing the leader backend JSON protocol."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendResponse"
ZERO_SHA256 = "0" * 64


class Lock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.stream: Any = None

    def __enter__(self) -> "Lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0)
        if os.name == "nt":
            import msvcrt
            self.stream.write(b"0")
            self.stream.flush()
            self.stream.seek(0)
            deadline = time.monotonic() + 5
            while True:
                try:
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
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


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def load(path: Path) -> tuple[dict[str, Any], bytes, str] | None:
    if not path.is_file():
        return None
    content = path.read_bytes()
    return json.loads(content), content, digest(content)


def atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def response(request: dict[str, Any], *, found: bool, committed: bool | None,
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


def main() -> int:
    mode = os.environ.get("PDR_TEST_LEADER_BACKEND_MODE", "normal")
    if mode == "timeout":
        time.sleep(10)
    if mode == "malformed":
        sys.stdout.write("not-json")
        return 0
    request = json.loads(sys.stdin.buffer.read())
    if request.get("product") != REQUEST_PRODUCT:
        return 2
    root = Path(os.environ["PDR_TEST_LEADER_BACKEND_ROOT"]).resolve()
    scope = root / request["authorityId"] / request["registryId"]
    current_path = scope / "current.json"
    operation = request["operation"]
    uncertain_marker = scope / ".commit-then-timeout"
    if (mode == "commit-then-timeout" and operation == "read-current"
            and uncertain_marker.is_file()):
        time.sleep(10)
    if operation == "read-current":
        loaded = load(current_path)
        result = response(request, found=loaded is not None, committed=None,
                          grant=loaded)
    elif operation == "read-grant":
        path = scope / "grants" / (
            f"{request['fencingToken']:020d}-{request['grantSha256']}.json"
        )
        loaded = load(path)
        result = response(request, found=loaded is not None, committed=None,
                          grant=loaded)
    else:
        with Lock(scope / ".cas.lock"):
            current = load(current_path)
            actual_token = current[0]["fencingToken"] if current else 0
            actual_sha = current[2] if current else ZERO_SHA256
            expected = (
                request["expectedCurrentToken"],
                request["expectedCurrentGrantSha256"],
            )
            if (actual_token, actual_sha) != expected:
                result = response(
                    request, found=current is not None, committed=False,
                    grant=current,
                )
            else:
                content = base64.b64decode(request["grantBase64"], validate=True)
                grant_document = json.loads(content)
                grant_sha = digest(content)
                if (grant_sha != request["grantSha256"]
                        or grant_document["fencingToken"]
                            != request["fencingToken"]
                        or request["fencingToken"] != actual_token + 1
                        or grant_document["previousGrantSha256"]
                            != (None if actual_token == 0 else actual_sha)):
                    result = response(
                        request, found=False, committed=None, passed=False,
                        error="CAS grant invariant failed",
                    )
                else:
                    blob = scope / "grants" / (
                        f"{request['fencingToken']:020d}-{grant_sha}.json"
                    )
                    blob.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        with blob.open("xb") as stream:
                            stream.write(content)
                            stream.flush()
                            os.fsync(stream.fileno())
                    except FileExistsError:
                        if blob.read_bytes() != content:
                            return 3
                    atomic(current_path, content)
                    if mode == "commit-then-timeout":
                        uncertain_marker.write_text("committed\n", encoding="utf-8")
                    result = response(
                        request, found=True, committed=True,
                        grant=(grant_document, content, grant_sha),
                    )
    if mode == "mismatch":
        result["requestId"] = "wrong-request-id"
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
