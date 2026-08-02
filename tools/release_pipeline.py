#!/usr/bin/env python3
"""Run and resume hash-bound PocoDDSRuntime release pipeline stages."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.new")
    try:
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def process_exists(process_id: int) -> bool:
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() != 87
    try:
        os.kill(process_id, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextlib.contextmanager
def state_lock(state_path: Path):
    lock = state_path.with_name(state_path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    for _ in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            existing = lock.read_text(encoding="ascii")
            match = re.search(r"^pid=(\d+)$", existing, re.MULTILINE)
            owner = int(match.group(1)) if match else 0
            if owner <= 0 or process_exists(owner):
                raise RuntimeError(f"release pipeline state is locked: {lock}")
            if lock.read_text(encoding="ascii") != existing:
                raise RuntimeError("release pipeline lock changed during recovery")
            lock.unlink()
    if descriptor < 0:
        raise RuntimeError(f"cannot acquire release pipeline lock: {lock}")
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        lock.unlink(missing_ok=True)


def source_fingerprint(source: Path) -> dict[str, Any]:
    revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=False)
    if revision.returncode:
        raise ValueError("release pipeline source root is not a Git worktree")
    tracked = subprocess.run(["git", "-C", str(source), "diff", "--name-only", "-z", "HEAD", "--"],
                             capture_output=True, check=False)
    untracked = subprocess.run(["git", "-C", str(source), "ls-files", "--others",
                                "--exclude-standard", "-z"], capture_output=True, check=False)
    paths = sorted(set(item.decode("utf-8", errors="surrogateescape")
                       for item in (tracked.stdout + untracked.stdout).split(b"\0") if item))
    value = hashlib.sha256()
    for relative in paths:
        value.update(relative.encode("utf-8", errors="surrogateescape") + b"\0")
        path = source / relative
        value.update(bytes.fromhex(digest(path)) if path.is_file() else b"<deleted>")
    return {"commit": revision.stdout.strip(), "worktreeSha256": value.hexdigest(),
            "changeCount": len(paths)}


def resolve_scoped(root: Path, value: str, label: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"release pipeline {label} escapes its root: {value}")
    return resolved


def load_plan(path: Path) -> tuple[dict[str, Any], Path, Path]:
    document = json.loads(path.resolve().read_text(encoding="utf-8"))
    if document.get("schemaVersion") != 1 or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*", str(document.get("pipelineId", ""))):
        raise ValueError("release pipeline plan identity is invalid")
    source = Path(str(document.get("sourceRoot", ""))).resolve()
    build = Path(str(document.get("buildRoot", ""))).resolve()
    if not source.is_dir() or not build.is_dir():
        raise ValueError("release pipeline source/build root does not exist")
    stages = document.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError("release pipeline has no stages")
    ids = []
    for stage in stages:
        if not isinstance(stage, dict) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]*", str(stage.get("id", ""))):
            raise ValueError("release pipeline stage identity is invalid")
        ids.append(stage["id"])
        command = stage.get("command")
        if (not isinstance(command, list) or not command or
                any(not isinstance(value, str) or "\x00" in value for value in command)):
            raise ValueError(f"release pipeline stage command is invalid: {stage['id']}")
        timeout = stage.get("timeoutSeconds", 600)
        if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 86400:
            raise ValueError(f"release pipeline stage timeout is invalid: {stage['id']}")
        for field in ("requiredInputs", "requiredOutputs"):
            values = stage.get(field, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError(f"release pipeline stage {field} is invalid: {stage['id']}")
            for value in values:
                resolve_scoped(build, value, field)
        if "workingDirectory" in stage:
            working = Path(stage["workingDirectory"])
            resolved = working.resolve() if working.is_absolute() else (source / working).resolve()
            if not (resolved == source or source in resolved.parents or resolved == build or build in resolved.parents):
                raise ValueError("release pipeline working directory escapes source/build roots")
    if len(set(ids)) != len(ids):
        raise ValueError("release pipeline stage ids are duplicated")
    return document, source, build


def file_evidence(build: Path, values: list[str]) -> list[dict[str, Any]]:
    result = []
    for value in values:
        path = resolve_scoped(build, value, "output")
        if not path.is_file():
            raise FileNotFoundError(f"release pipeline required file is missing: {path}")
        result.append({"path": value, "size": path.stat().st_size, "sha256": digest(path)})
    return result


def verify_completed_outputs(build: Path, stage_state: dict[str, Any]) -> None:
    for item in stage_state.get("outputs", []):
        path = resolve_scoped(build, str(item.get("path", "")), "checkpoint output")
        if (not path.is_file() or path.stat().st_size != item.get("size") or
                digest(path) != item.get("sha256")):
            raise ValueError(f"completed release pipeline output changed: {path}")


def _execute(args: argparse.Namespace, resume: bool) -> int:
    if not args.confirm_run:
        raise ValueError("release pipeline execution requires --confirm-run")
    plan_path, state_path = args.plan.resolve(), args.state.resolve()
    plan, source, build = load_plan(plan_path)
    plan_sha, fingerprint = digest(plan_path), source_fingerprint(source)
    if resume:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("planSha256") != plan_sha or state.get("source") != fingerprint:
            raise ValueError("release pipeline plan or source changed; resume is unsafe")
    else:
        if state_path.exists():
            raise FileExistsError("release pipeline state already exists; use resume or a new state path")
        state = {"schemaVersion": 1, "operation": "release-pipeline",
                 "pipelineId": plan["pipelineId"], "status": "running",
                 "startedAt": datetime.now(timezone.utc).isoformat(), "plan": str(plan_path),
                 "planSha256": plan_sha, "source": fingerprint, "stages": []}
        atomic_json(state_path, state)
    existing = {item["id"]: item for item in state["stages"]}
    logs = state_path.parent / f"{state_path.stem}.logs"
    logs.mkdir(parents=True, exist_ok=True)
    for stage in plan["stages"]:
        stage_id = stage["id"]
        previous = existing.get(stage_id)
        if previous and previous.get("status") == "passed":
            verify_completed_outputs(build, previous)
            continue
        file_evidence(build, stage.get("requiredInputs", []))
        working_value = stage.get("workingDirectory")
        if working_value:
            working_path = Path(working_value)
            working = (working_path.resolve() if working_path.is_absolute() else
                       (source / working_path).resolve())
        else:
            working = source
        log_path = logs / f"{stage_id}.log"
        started = time.monotonic()
        stage_state = {"id": stage_id, "status": "running",
                       "startedAt": datetime.now(timezone.utc).isoformat(),
                       "command": stage["command"], "log": str(log_path)}
        if previous:
            state["stages"][state["stages"].index(previous)] = stage_state
        else:
            state["stages"].append(stage_state)
        atomic_json(state_path, state)
        try:
            completed = subprocess.run(stage["command"], cwd=working, capture_output=True, text=True,
                                       timeout=float(stage.get("timeoutSeconds", 600)), check=False)
            log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8", errors="replace")
            stage_state.update({"exitCode": completed.returncode,
                                "durationSeconds": round(time.monotonic() - started, 3)})
            if completed.returncode:
                stage_state["status"] = "failed"
                state["status"] = "failed"
                atomic_json(state_path, state)
                print(f"RELEASE_PIPELINE_STAGE_FAILED id={stage_id} exit={completed.returncode}",
                      file=sys.stderr)
                return 1
            stage_state["outputs"] = file_evidence(build, stage.get("requiredOutputs", []))
            stage_state["status"] = "passed"
            stage_state["finishedAt"] = datetime.now(timezone.utc).isoformat()
            atomic_json(state_path, state)
        except subprocess.TimeoutExpired as error:
            log_path.write_text((error.stdout or "") + (error.stderr or ""), encoding="utf-8")
            stage_state.update({"status": "timed-out",
                                "durationSeconds": round(time.monotonic() - started, 3)})
            state["status"] = "failed"
            atomic_json(state_path, state)
            return 1
    state["status"] = "complete"
    state["finishedAt"] = datetime.now(timezone.utc).isoformat()
    atomic_json(state_path, state)
    print(f"RELEASE_PIPELINE_COMPLETE stages={len(plan['stages'])} state={state_path}")
    return 0


def execute(args: argparse.Namespace, resume: bool) -> int:
    if not args.confirm_run:
        raise ValueError("release pipeline execution requires --confirm-run")
    with state_lock(args.state.resolve()):
        return _execute(args, resume)


def status(args: argparse.Namespace) -> int:
    state = json.loads(args.state.resolve().read_text(encoding="utf-8"))
    summary = {"pipelineId": state.get("pipelineId"), "status": state.get("status"),
               "stages": [{"id": item.get("id"), "status": item.get("status")}
                          for item in state.get("stages", [])]}
    print(json.dumps(summary, indent=2))
    return 0 if state.get("status") == "complete" else 1


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name, resume in (("run", False), ("resume", True)):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--state", type=Path, required=True)
        command.add_argument("--confirm-run", action="store_true")
        command.set_defaults(handler=lambda args, value=resume: execute(args, value))
    state = commands.add_parser("status")
    state.add_argument("--state", type=Path, required=True)
    state.set_defaults(handler=status)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"RELEASE_PIPELINE_ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
