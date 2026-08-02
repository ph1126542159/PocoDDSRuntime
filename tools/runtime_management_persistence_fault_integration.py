#!/usr/bin/env python3
"""Prove corrupt management persistence degrades safely without removing diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-smoke", required=True, type=Path)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--working-directory", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--install-bin", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args()


def run_case(args: argparse.Namespace, name: str, corrupt_ledger: bool,
             corrupt_content: str) -> dict[str, object]:
    case_report = args.report.with_name(f"{args.report.stem}-{name}.json")
    ledger = args.report.with_name(f"{args.report.stem}-{name}-idempotency.json")
    tasks = args.report.with_name(f"{args.report.stem}-{name}-tasks.json")
    for path in (ledger, tasks,
                 Path(str(ledger) + ".new"), Path(str(tasks) + ".new"),
                 Path(str(ledger) + ".previous"), Path(str(tasks) + ".previous"),
                 Path(str(ledger) + ".previous.new"), Path(str(tasks) + ".previous.new")):
        path.unlink(missing_ok=True)
    corrupt_path = ledger if corrupt_ledger else tasks
    corrupt_path.write_text(corrupt_content, encoding="utf-8")
    operation = ('/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"restart"}'
                 if corrupt_ledger else
                 '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"start","async":true}')
    expected_code = ("PDR-HEALTH-MANAGEMENT-IDEMPOTENCY-PERSISTENCE_FAILED"
                     if corrupt_ledger else
                     "PDR-HEALTH-MANAGEMENT-TASK-PERSISTENCE_FAILED")
    expected_error = ("管理幂等账本需要运维恢复" if corrupt_ledger else
                      "管理任务快照需要运维恢复")
    command = [
        sys.executable, str(args.runtime_smoke),
        "--executable", str(args.executable),
        "--working-directory", str(args.working_directory),
        "--config", str(args.config),
        "--timeout", "15", "--stability-window", "1", "--clear-code-cache",
        "--force-shutdown",
        "--path", str(args.install_bin), "--path", str(args.working_directory),
        "--set", "pdr.mqtt.count=0", "--set", "pdr.ros.count=0",
        "--set", "pdr.management.authentication.required=true",
        "--set", "pdr.management.authentication.tokenEnvironment=PDR_TEST_MANAGEMENT_TOKEN",
        "--set", "pdr.management.idempotency.requireRequestId=true",
        "--set", f"pdr.management.idempotency.persistence.path={ledger.as_posix()}",
        "--set", f"pdr.management.tasks.persistence.path={tasks.as_posix()}",
        "--bearer-token-environment", "PDR_TEST_MANAGEMENT_TOKEN",
        "--endpoint", "/api/v1/management-tasks?limit=10",
        "--endpoint", "/health/detail",
        "--expect-status", "/health/ready=503",
        "--post", operation, "--post-response-status", "1=503",
        "--require-body", expected_code,
        "--require-body", expected_error,
        "--require-body", '"recoveryRequired":true',
        "--require-body", '"previousAvailable":false',
        "--report", str(case_report),
    ]
    environment = os.environ.copy()
    environment["PDR_TEST_MANAGEMENT_TOKEN"] = "pdr-persistence-fault-token"
    completed = subprocess.run(command, text=True, capture_output=True, check=False,
                               env=environment)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    report = json.loads(case_report.read_text(encoding="utf-8")) if case_report.exists() else {}
    report["exitCode"] = completed.returncode
    report["corruptFilePreserved"] = (
        corrupt_path.exists() and corrupt_path.read_text(encoding="utf-8") == corrupt_content
    )
    report["passed"] = (report.get("passed") is True and completed.returncode == 0 and
                        report["corruptFilePreserved"])
    return report


def run_v1_migration_case(args: argparse.Namespace) -> dict[str, object]:
    case_report = args.report.with_name(f"{args.report.stem}-v1-migration.json")
    ledger = args.report.with_name(f"{args.report.stem}-v1-migration-idempotency.json")
    tasks = args.report.with_name(f"{args.report.stem}-v1-migration-tasks.json")
    for path in (ledger, tasks, Path(str(ledger) + ".previous"),
                 Path(str(tasks) + ".previous")):
        path.unlink(missing_ok=True)
    ledger.write_text('{"schemaVersion":1,"requests":[]}', encoding="utf-8")
    tasks.write_text('{"schemaVersion":1,"tasks":[]}', encoding="utf-8")
    command = [
        sys.executable, str(args.runtime_smoke),
        "--executable", str(args.executable),
        "--working-directory", str(args.working_directory),
        "--config", str(args.config),
        "--timeout", "15", "--stability-window", "1", "--clear-code-cache",
        "--force-shutdown",
        "--path", str(args.install_bin), "--path", str(args.working_directory),
        "--set", "pdr.mqtt.count=0", "--set", "pdr.ros.count=0",
        "--set", f"pdr.management.idempotency.persistence.path={ledger.as_posix()}",
        "--set", f"pdr.management.tasks.persistence.path={tasks.as_posix()}",
        "--endpoint", "/api/v1/management-tasks?limit=10",
        "--require-body", '"integrityAlgorithm":"SHA-256"',
        "--require-body", '"schemaVersion":2',
        "--require-body", '"recoveryRequired":false',
        "--require-body", '"previousAvailable":true',
        "--report", str(case_report),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False,
                               env=os.environ.copy())
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    runtime_report = (json.loads(case_report.read_text(encoding="utf-8"))
                      if case_report.exists() else {})
    ledger_v2 = json.loads(ledger.read_text(encoding="utf-8"))
    tasks_v2 = json.loads(tasks.read_text(encoding="utf-8"))
    ledger_previous = Path(str(ledger) + ".previous")
    tasks_previous = Path(str(tasks) + ".previous")
    migrated = all(
        snapshot.get("schemaVersion") == 2 and
        len(str(snapshot.get("contentSha256", ""))) == 64
        for snapshot in (ledger_v2, tasks_v2)
    )
    return {
        "passed": (completed.returncode == 0 and runtime_report.get("passed") is True and
                   migrated and ledger_previous.exists() and tasks_previous.exists() and
                   json.loads(ledger_previous.read_text(encoding="utf-8")).get(
                       "schemaVersion") == 1 and
                   json.loads(tasks_previous.read_text(encoding="utf-8")).get(
                       "schemaVersion") == 1),
        "runtime": runtime_report,
        "ledgerMigrated": ledger_v2.get("schemaVersion") == 2,
        "tasksMigrated": tasks_v2.get("schemaVersion") == 2,
        "previousSnapshotsPreserved": ledger_previous.exists() and tasks_previous.exists(),
    }


def main() -> int:
    args = parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    zero_digest = "0" * 64
    ledger_syntax = run_case(args, "ledger-syntax-corrupt", True, "{corrupt")
    ledger_integrity = run_case(
        args, "ledger-integrity-corrupt", True,
        json.dumps({"schemaVersion": 2, "contentSha256": zero_digest, "requests": []},
                   separators=(",", ":")),
    )
    tasks_schema = run_case(
        args, "tasks-schema-corrupt", False,
        '{"schemaVersion":99,"tasks":[]}',
    )
    tasks_integrity = run_case(
        args, "tasks-integrity-corrupt", False,
        json.dumps({"schemaVersion": 2, "contentSha256": zero_digest, "tasks": []},
                   separators=(",", ":")),
    )
    migration = run_v1_migration_case(args)
    result = {
        "schemaVersion": 1,
        "ledgerCorruptionIsolated": all(case.get("passed") is True for case in
                                        (ledger_syntax, ledger_integrity)),
        "taskCorruptionIsolated": all(case.get("passed") is True for case in
                                      (tasks_schema, tasks_integrity)),
        "integrityTamperingDetected": (ledger_integrity.get("passed") is True and
                                       tasks_integrity.get("passed") is True),
        "v1MigrationPassed": migration.get("passed") is True,
        "cases": {
            "ledgerSyntax": ledger_syntax,
            "ledgerIntegrity": ledger_integrity,
            "tasksSchema": tasks_schema,
            "tasksIntegrity": tasks_integrity,
            "v1Migration": migration,
        },
    }
    result["passed"] = (result["ledgerCorruptionIsolated"] and
                        result["taskCorruptionIsolated"] and
                        result["integrityTamperingDetected"] and
                        result["v1MigrationPassed"])
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    print("RUNTIME_MANAGEMENT_PERSISTENCE_FAULT_" + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
