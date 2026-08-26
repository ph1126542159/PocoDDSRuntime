#!/usr/bin/env python3
"""Small persistent etcdctl v3 model for adapter transaction tests."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


class Lock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.stream: Any = None

    def __enter__(self) -> "Lock":
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


def atomic(path: Path, document: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".state.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load(path: Path) -> dict[str, str]:
    return json.loads(path.read_bytes()) if path.is_file() else {}


def command_index(arguments: list[str]) -> int:
    for index, value in enumerate(arguments):
        if value in {"version", "get", "txn", "endpoint"}:
            return index
    raise ValueError("fake etcdctl command is missing")


def parse_put(line: str) -> tuple[str, str]:
    if not line.startswith("put "):
        raise ValueError("fake etcdctl only supports transaction puts")
    decoder = json.JSONDecoder()
    key, offset = decoder.raw_decode(line, 4)
    while offset < len(line) and line[offset].isspace():
        offset += 1
    value, end = decoder.raw_decode(line, offset)
    if line[end:].strip() or not isinstance(key, str) or not isinstance(value, str):
        raise ValueError("fake etcdctl put is malformed")
    return key, value


def compare(line: str, state: dict[str, str]) -> bool:
    match = re.fullmatch(r"(version|value)\((.+)\) = (.+)", line)
    if match is None:
        raise ValueError("fake etcdctl comparison is malformed")
    key = json.loads(match.group(2))
    expected = json.loads(match.group(3))
    if match.group(1) == "version":
        return ("1" if key in state else "0") == expected
    return state.get(key) == expected


def main() -> int:
    arguments = sys.argv[1:]
    index = command_index(arguments)
    command = arguments[index]
    if command == "version":
        print("etcdctl version: 3.6.0")
        print("API version: 3.6")
        return 0
    root = Path(os.environ["PDR_TEST_ETCDCTL_ROOT"]).resolve()
    state_path = root / "state.json"
    if command == "get":
        key = arguments[index + 1]
        with Lock(root / ".lock"):
            state = load(state_path)
            value = state.get(key)
        result: dict[str, Any] = {"count": 1 if value is not None else 0}
        if value is not None:
            result["kvs"] = [{
                "key": base64.b64encode(key.encode()).decode("ascii"),
                "value": base64.b64encode(value.encode()).decode("ascii"),
            }]
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    if command == "endpoint":
        endpoint_flag = next(
            item for item in arguments if item.startswith("--endpoints=")
        )
        endpoints = endpoint_flag.split("=", 1)[1].split(",")
        mode = os.environ.get("PDR_TEST_ETCDCTL_MODE", "normal")
        if "health" in arguments:
            for item in endpoints:
                print(f"{item} is healthy: successfully committed proposal")
            return 0
        statuses = []
        for offset, item in enumerate(endpoints, start=1):
            statuses.append({
                "Endpoint": item,
                "Status": {
                    "header": {
                        "cluster_id": 9001 if mode != "cluster-mismatch"
                            or offset < len(endpoints) else 9002,
                        "member_id": 1000 + offset,
                        "revision": 42,
                        "raft_term": 7,
                    },
                    "version": "3.6.0", "leader": 1002,
                    "raftTerm": 7, "raftIndex": 50,
                    "raftAppliedIndex": 50, "isLearner": False,
                    "errors": [],
                },
            })
        print(json.dumps(statuses, sort_keys=True, separators=(",", ":")))
        return 0
    content = sys.stdin.read()
    sections = content.split("\n\n")
    if len(sections) < 3:
        raise ValueError("fake etcdctl transaction sections are malformed")
    comparisons = [line for line in sections[0].splitlines() if line]
    operations = [line for line in sections[1].splitlines() if line]
    with Lock(root / ".lock"):
        state = load(state_path)
        succeeded = all(compare(line, state) for line in comparisons)
        if succeeded:
            updated = dict(state)
            for line in operations:
                key, value = parse_put(line)
                updated[key] = value
            atomic(state_path, updated)
    print("SUCCESS" if succeeded else "FAILURE")
    if succeeded:
        for _ in operations:
            print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
