#!/usr/bin/env python3
"""Verify offline lifecycle journal inspection, backup, locking and CLI routing."""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--seed-executable", required=True)
    parser.add_argument("--pdr", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--report", required=True)
    return parser.parse_args()


def environment(paths: list[str]) -> dict[str, str]:
    result = os.environ.copy()
    resolved = [str(Path(value).resolve()) for value in paths]
    result["PATH"] = os.pathsep.join(resolved + [result.get("PATH", "")])
    return result


def run(command: list[str], env: dict[str, str], expected: int = 0) -> dict:
    completed = subprocess.run(command, env=env, capture_output=True, text=True,
                               check=False, timeout=30)
    if completed.returncode != expected:
        raise RuntimeError(
            f"command returned {completed.returncode}, expected {expected}: "
            f"{' '.join(command)}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"command did not return JSON: {completed.stdout}") from error


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    args = parse_args()
    tool = str(Path(args.tool).resolve())
    seed = str(Path(args.seed_executable).resolve())
    pdr = str(Path(args.pdr).resolve())
    env = environment(args.path)
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, object] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="case-", dir=workspace) as temporary:
            root = Path(temporary)
            source = root / "maintenance.sqlite"
            backup = root / "maintenance-'quoted'.sqlite"
            wrapper_backup = root / "maintenance-wrapper-backup.sqlite"
            corrupt = root / "maintenance-corrupt.sqlite"
            semantic_corrupt = root / "maintenance-semantic-corrupt.sqlite"
            missing = root / "missing.sqlite"
            occupied = root / "occupied.sqlite"

            subprocess.run([
                seed, "--database", str(source), "--status", "draining",
                "--target", "provider.bundle", "--consumer", "consumer.bundle",
            ], env=env, check=True, capture_output=True, text=True, timeout=30)
            source_digest = digest(source)
            checked = run([
                tool, "--action", "check", "--database", str(source),
                "--limit", "10",
            ], env)
            if (not checked.get("healthy") or checked["store"]["openPlans"] != 1 or
                    checked["returnedPlans"] != 1 or checked["truncated"]):
                raise RuntimeError("offline check returned an invalid journal snapshot")
            if digest(source) != source_digest:
                raise RuntimeError("offline check modified the source database")

            copied = run([
                tool, "--action", "backup", "--database", str(source),
                "--destination", str(backup),
            ], env)
            if (not copied.get("healthy") or copied["source"]["planRecords"] != 1 or
                    copied["backup"]["planRecords"] != 1 or copied["bytes"] <= 0):
                raise RuntimeError("consistent backup did not preserve the source snapshot")
            backup_digest = digest(backup)
            duplicate = run([
                tool, "--action", "backup", "--database", str(source),
                "--destination", str(backup),
            ], env, expected=2)
            if duplicate.get("healthy") or digest(backup) != backup_digest:
                raise RuntimeError("duplicate backup target was overwritten")

            same = run([
                tool, "--action", "backup", "--database", str(source),
                "--destination", str(source),
            ], env, expected=2)
            if same.get("healthy"):
                raise RuntimeError("source database was accepted as its own backup")

            missing_result = run([
                tool, "--action", "check", "--database", str(missing),
            ], env, expected=2)
            if missing_result.get("healthy") or missing.exists():
                raise RuntimeError("missing database was created by offline inspection")

            corrupt.write_bytes(b"not-a-sqlite-database")
            corrupt_result = run([
                tool, "--action", "check", "--database", str(corrupt),
            ], env, expected=2)
            if corrupt_result.get("healthy"):
                raise RuntimeError("corrupt database passed integrity inspection")

            run([
                tool, "--action", "backup", "--database", str(source),
                "--destination", str(semantic_corrupt),
            ], env)
            with closing(sqlite3.connect(semantic_corrupt)) as connection:
                connection.execute(
                    "UPDATE lifecycle_plans SET status='restored' WHERE id='maintenance-1'"
                )
                connection.commit()
            semantic_result = run([
                tool, "--action", "check", "--database", str(semantic_corrupt),
            ], env, expected=2)
            if semantic_result.get("healthy"):
                raise RuntimeError("semantic plan index corruption passed inspection")

            routed = run([
                sys.executable, pdr, "lifecycle", "store-check",
                "--database", str(backup), "--limit", "10", "--tool", tool,
            ], env)
            if not routed.get("healthy") or routed["store"]["planRecords"] != 1:
                raise RuntimeError("pdr lifecycle store-check routing failed")
            routed_backup = run([
                sys.executable, pdr, "lifecycle", "store-backup",
                "--database", str(backup), "--destination", str(wrapper_backup),
                "--tool", tool,
            ], env)
            if not routed_backup.get("healthy"):
                raise RuntimeError("pdr lifecycle store-backup routing failed")

            holder = subprocess.Popen([
                seed, "--database", str(occupied), "--status", "draining",
                "--target", "occupied.bundle", "--hold-milliseconds", "2000",
            ], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                if not holder.stdout or not holder.stdout.readline().strip():
                    raise RuntimeError("lease holder did not become ready")
                occupied_result = run([
                    tool, "--action", "check", "--database", str(occupied),
                ], env, expected=2)
                if occupied_result.get("healthy"):
                    raise RuntimeError("inspection bypassed the active owner lease")
            finally:
                holder.wait(timeout=10)
                if holder.returncode != 0:
                    stderr = holder.stderr.read() if holder.stderr else ""
                    raise RuntimeError(f"lease holder failed: {stderr}")

            invalid_limit = run([
                tool, "--action", "check", "--database", str(source),
                "--limit", "0",
            ], env, expected=2)
            if invalid_limit.get("healthy"):
                raise RuntimeError("unsafe history limit was accepted")

            evidence = {
                "healthy": True,
                "check": True,
                "backup": True,
                "backupVerified": True,
                "sourceUnchanged": True,
                "missingRejected": True,
                "corruptRejected": True,
                "semanticCorruptRejected": True,
                "occupiedRejected": True,
                "overwriteRejected": True,
                "pdrRouting": True,
                "planRecords": checked["store"]["planRecords"],
                "backupBytes": copied["bytes"],
            }
        report = Path(args.report).resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print("RUNTIME_LIFECYCLE_STORE_PASS check=1 backup=1 lock=1 corruption=1 routing=1")
        return 0
    except Exception as error:  # noqa: BLE001 - integration evidence needs one failure path
        evidence = {"healthy": False, "error": str(error), **evidence}
        report = Path(args.report).resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"RUNTIME_LIFECYCLE_STORE_FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
