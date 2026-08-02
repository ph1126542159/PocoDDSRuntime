#!/usr/bin/env python3
"""Exercise recovery-point restore and post-start acceptance with a real Runtime."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--pdr", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--working-directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--install-bin", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def stop_process(process: subprocess.Popen[bytes]) -> int:
    if process.poll() is not None:
        return int(process.returncode)
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        return process.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
        try:
            return process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait(timeout=5)


def main() -> int:
    args = parse_args()
    workspace = args.workspace.resolve()
    report_path = args.report.resolve()
    source = workspace / "source"
    target = workspace / "target"
    recovery_points = workspace / "recovery-points"
    archives = workspace / "pre-restore-evidence"
    operation_audit = workspace / "restore-operations.jsonl"
    backup_report = workspace / "backup-report.json"
    restore_report = workspace / "restore-report.json"
    acceptance_report = workspace / "acceptance-report.json"
    runtime_log = workspace / "runtime.log"
    result: dict[str, object] = {"schemaVersion": 1, "passed": False}
    process: subprocess.Popen[bytes] | None = None
    log_stream = None
    try:
        if (workspace.parent != report_path.parent or
                workspace.name != "runtime-restore-acceptance-workspace"):
            raise ValueError("workspace must be the dedicated report-side acceptance workspace")
        if workspace.exists():
            shutil.rmtree(workspace)
        source.mkdir(parents=True)
        (source / "management-tasks.json").write_text(
            '{"schemaVersion":1,"tasks":[]}\n', encoding="utf-8", newline="\n"
        )
        (source / "management-idempotency.json").write_text(
            '{"schemaVersion":1,"requests":[]}\n', encoding="utf-8", newline="\n"
        )
        shutil.copy2(args.config.resolve(), source / "pdr-runtime.properties")
        (source / "management-audit.jsonl").write_text("", encoding="utf-8")
        backup = run([
            str(args.python), str(args.pdr), "persistence", "backup",
            "--tasks", str(source / "management-tasks.json"),
            "--idempotency", str(source / "management-idempotency.json"),
            "--configuration", str(source / "pdr-runtime.properties"),
            "--management-audit", str(source / "management-audit.jsonl"),
            "--output", str(recovery_points), "--operator", "integration-test",
            "--confirm-runtime-stopped", "--report", str(backup_report),
        ])
        if backup.returncode != 0:
            raise RuntimeError(f"backup failed: {backup.stdout}{backup.stderr}")
        backup_evidence = json.loads(backup_report.read_text(encoding="utf-8"))
        restore = run([
            str(args.python), str(args.pdr), "persistence", "restore-recovery-point",
            str(backup_evidence["path"]),
            "--tasks", str(target / "management-tasks.json"),
            "--idempotency", str(target / "management-idempotency.json"),
            "--configuration", str(target / "pdr-runtime.properties"),
            "--management-audit", str(target / "management-audit.jsonl"),
            "--archive-output", str(archives), "--operation-audit", str(operation_audit),
            "--operator", "integration-test", "--expected-manifest-sha256",
            str(backup_evidence["verification"]["manifestSha256"]),
            "--confirm-runtime-stopped", "--report", str(restore_report),
        ])
        if restore.returncode != 0:
            raise RuntimeError(f"restore failed: {restore.stdout}{restore.stderr}")
        restore_evidence = json.loads(restore_report.read_text(encoding="utf-8"))
        port = free_port()
        overlay = workspace / "runtime.properties"
        overlay.write_text(
            (target / "pdr-runtime.properties").read_text(encoding="utf-8") + "\n" +
            "\n".join([
                "osp.web.server.host = 127.0.0.1", f"osp.web.server.port = {port}",
                "pdr.management.authentication.required = false",
                f"pdr.management.tasks.persistence.path = {(target / 'management-tasks.json').as_posix()}",
                f"pdr.management.idempotency.persistence.path = {(target / 'management-idempotency.json').as_posix()}",
                f"pdr.management.audit.path = {(target / 'management-audit.jsonl').as_posix()}",
                "pdr.mqtt.count = 0", "pdr.ros.count = 0", "pdr.udp.count = 0",
            ]) + "\n", encoding="utf-8", newline="\n",
        )
        environment = os.environ.copy()
        environment["PATH"] = os.pathsep.join([
            str(args.install_bin.resolve()), str(args.working_directory.resolve()),
            environment.get("PATH", ""),
        ])
        option = f"/config-file={overlay}" if os.name == "nt" else f"--config-file={overlay}"
        log_stream = runtime_log.open("wb")
        process = subprocess.Popen(
            [str(args.executable.resolve()), option], cwd=args.working_directory.resolve(),
            env=environment, stdout=log_stream, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        acceptance = run([
            str(args.python), str(args.pdr), "persistence", "validate-restored-runtime",
            "--base-url", f"http://127.0.0.1:{port}",
            "--restore-report", str(restore_report), "--operation-audit", str(operation_audit),
            "--expected-restore-id", str(restore_evidence["restoreId"]),
            "--operator", "integration-validator", "--timeout", "20",
            "--request-timeout", "1", "--poll-interval", "0.2",
            "--report", str(acceptance_report),
        ])
        acceptance_evidence = json.loads(acceptance_report.read_text(encoding="utf-8"))
        task_snapshot = json.loads((target / "management-tasks.json").read_text(encoding="utf-8"))
        ledger_snapshot = json.loads(
            (target / "management-idempotency.json").read_text(encoding="utf-8")
        )
        result.update({
            "backupPassed": backup_evidence.get("passed") is True,
            "restorePassed": restore_evidence.get("passed") is True,
            "acceptanceExitCode": acceptance.returncode,
            "acceptanceVerdict": acceptance_evidence.get("verdict"),
            "approvedForManagementWrites": acceptance_evidence.get(
                "approvedForManagementWrites"),
            "taskSchemaVersion": task_snapshot.get("schemaVersion"),
            "idempotencySchemaVersion": ledger_snapshot.get("schemaVersion"),
            "restoreId": restore_evidence.get("restoreId"),
            "runtimePid": process.pid,
        })
        result["passed"] = all([
            result["backupPassed"], result["restorePassed"], acceptance.returncode == 0,
            result["acceptanceVerdict"] == "APPROVED",
            result["approvedForManagementWrites"] is True,
            result["taskSchemaVersion"] == 2, result["idempotencySchemaVersion"] == 2,
        ])
        time.sleep(1.0)
    except Exception as error:
        result["error"] = str(error)
    finally:
        if process is not None:
            result["runtimeExitCode"] = stop_process(process)
        if log_stream is not None:
            log_stream.close()
        result["temporaryArtifacts"] = len([
            path for path in workspace.rglob("*")
            if ".restore-" in path.name or ".rollback-" in path.name or
            (path.name.startswith(".") and path.name.endswith(".new"))
        ]) if workspace.exists() else 0
        result["passed"] = (bool(result.get("passed")) and result["temporaryArtifacts"] == 0 and
                            result.get("runtimeExitCode") == 0)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8", newline="\n")
    print("RUNTIME_RESTORE_ACCEPTANCE_" + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
