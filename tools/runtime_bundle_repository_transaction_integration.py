#!/usr/bin/env python3
"""Installed-tree acceptance for safe Bundle repository transactions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def replace_property(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    prefix = key + " ="
    found = False
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key} = {value}"
            found = True
    if not found:
        lines.append(f"{key} = {value}")
    return "\n".join(lines) + "\n"


def read_journal(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def journal_when(path: Path, state: str, transaction_id: str | None = None) -> dict[str, str] | None:
    journal = read_journal(path)
    if journal.get("state") != state:
        return None
    if transaction_id is not None and journal.get("transactionId") != transaction_id:
        return None
    return journal


def wait_for(predicate, timeout: float, description: str):
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as error:  # transient startup/HTTP failures are expected
            last_error = error
        time.sleep(0.2)
    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"timed out waiting for {description}{detail}")


def health(port: int) -> dict[str, object] | None:
    with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=1.0) as response:
        if response.status != 200:
            return None
        return json.loads(response.read().decode("utf-8"))


def start_runtime(executable: Path, work_dir: Path, suffix: str) -> tuple[subprocess.Popen[bytes], object, object]:
    stdout = (work_dir / f"runtime-{suffix}.stdout.log").open("wb")
    stderr = (work_dir / f"runtime-{suffix}.stderr.log").open("wb")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [str(executable)], cwd=work_dir, stdout=stdout, stderr=stderr, creationflags=flags
    )
    return process, stdout, stderr


def stop_runtime(process: subprocess.Popen[bytes], stdout, stderr) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    stdout.close()
    stderr.close()


def run(args: argparse.Namespace) -> dict[str, object]:
    source_dir = args.source_dir.resolve()
    work_dir = args.work_dir.resolve()
    if work_dir.exists():
        shutil.rmtree(work_dir)
    shutil.copytree(source_dir, work_dir)
    for mutable in ("data", "logs", "codeCache"):
        path = work_dir / mutable
        if path.exists():
            shutil.rmtree(path)
    (work_dir / "data").mkdir()
    (work_dir / "logs").mkdir()
    (work_dir / "empty-subprocesses.properties").write_text("# empty\n", encoding="utf-8")

    port = free_port()
    config = work_dir / "pdr-runtime.properties"
    text = config.read_text(encoding="utf-8")
    for key, value in (
        ("osp.bundleMonitor.enabled", "true"),
        ("osp.bundleMonitor.intervalMilliseconds", "250"),
        ("osp.bundleMonitor.stableScanCount", "2"),
        ("osp.bundleMonitor.stateDirectory", "${application.dir}data/bundle-manager/"),
        ("osp.bundleMonitor.inProcessReloadEnabled", "false"),
        ("osp.web.server.port", str(port)),
        ("pdr.subprocess.configuration", "${application.dir}empty-subprocesses.properties"),
    ):
        text = replace_property(text, key, value)
    config.write_text(text, encoding="utf-8")

    executable = work_dir / args.runtime.name
    journal_path = work_dir / "data" / "bundle-manager" / "transaction.properties"
    lkg = work_dir / "data" / "bundle-manager" / "last-known-good"
    bundles = work_dir / "bundles"
    process, stdout, stderr = start_runtime(executable, work_dir, "initial")
    evidence: dict[str, object] = {"port": port}
    try:
        evidence["startupHealth"] = wait_for(lambda: health(port), 45, "initial readiness")
        startup = wait_for(
            lambda: journal_when(journal_path, "committed"),
            15,
            "startup Bundle transaction commit",
        )
        evidence["startup"] = startup
        evidence["lkgBundleCount"] = len(list(lkg.iterdir()))
        if evidence["lkgBundleCount"] != int(startup["bundleCount"]):
            raise RuntimeError("LKG inventory count does not match startup journal")

        broken = bundles / "broken.bndl"
        broken.write_text("not a bundle archive\n", encoding="utf-8")
        rejected = wait_for(
            lambda: journal_when(journal_path, "rejected"),
            15,
            "malformed Bundle rejection",
        )
        evidence["rejected"] = rejected
        evidence["healthAfterReject"] = health(port)
        if not evidence["healthAfterReject"]:
            raise RuntimeError("Runtime lost readiness after fail-before-mutation rejection")

        broken.unlink()
        deferred = wait_for(
            lambda: journal_when(journal_path, "restartRequired"),
            15,
            "restart-required transaction",
        )
        evidence["restartRequired"] = deferred
        evidence["healthWhileDeferred"] = health(port)
        if not evidence["healthWhileDeferred"]:
            raise RuntimeError("Runtime lost readiness while Bundle change was deferred")
        if process.poll() is not None:
            raise RuntimeError(f"Runtime exited during safe deferred transaction: {process.returncode}")
    finally:
        stop_runtime(process, stdout, stderr)

    process, stdout, stderr = start_runtime(executable, work_dir, "restart")
    try:
        evidence["restartHealth"] = wait_for(lambda: health(port), 45, "restart readiness")
        evidence["restartCommit"] = wait_for(
            lambda: journal_when(journal_path, "committed", "startup"),
            15,
            "restart Bundle transaction commit",
        )
        if process.poll() is not None:
            raise RuntimeError(f"Runtime exited after restart commit: {process.returncode}")
    finally:
        stop_runtime(process, stdout, stderr)

    evidence["result"] = "PASS"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return evidence


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        evidence = run(args)
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(f"bundle repository transaction acceptance failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
