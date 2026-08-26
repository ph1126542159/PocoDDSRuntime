#!/usr/bin/env python3
"""Verify central Scheduler Runtime registration, status, auth and managed tasks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


OPERATOR_ENV = "PDR_SCHEDULER_OPERATOR_TOKEN"
READER_ENV = "PDR_SCHEDULER_READER_TOKEN"
ENDPOINT = "/api/v1/scheduled-tasks"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--runtime-smoke", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--working-directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def base_command(args: argparse.Namespace, report: Path, log: Path) -> list[str]:
    command = [
        args.python, str(args.runtime_smoke),
        "--executable", str(args.executable),
        "--working-directory", str(args.working_directory),
        "--config", str(args.config),
        "--port", "0",
        "--timeout", "15",
        "--stability-window", "1",
        "--shutdown-timeout", "10",
        "--clear-code-cache",
        "--set", "pdr.management.authentication.required=true",
        "--set", "pdr.management.authentication.principals.count=2",
        "--set", "pdr.management.authentication.principals.0.id=scheduler-operator",
        "--set", f"pdr.management.authentication.principals.0.tokenEnvironment={OPERATOR_ENV}",
        "--set", "pdr.management.authentication.principals.0.permissions=resource.read",
        "--set", "pdr.management.authentication.principals.1.id=task-reader",
        "--set", f"pdr.management.authentication.principals.1.tokenEnvironment={READER_ENV}",
        "--set", "pdr.management.authentication.principals.1.permissions=task.read",
        "--endpoint", ENDPOINT,
        "--require-log", "Managed scheduler runtime started with one central timer thread",
        "--report", str(report),
        "--log", str(log),
    ]
    for value in args.path:
        command.extend(("--path", value))
    return command


def run(command: list[str], environment: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(command, env=environment, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError("runtime smoke failed\n" + completed.stdout + "\n" + completed.stderr)
    report = Path(command[command.index("--report") + 1])
    return json.loads(report.read_text(encoding="utf-8"))


def response_body(report: dict[str, object]) -> dict[str, object]:
    for probe in report.get("probes", []):
        if isinstance(probe, dict) and probe.get("endpoint") == ENDPOINT:
            body = json.loads(str(probe.get("body", "{}")))
            if isinstance(body, dict):
                return body
    raise RuntimeError("scheduler response body was not captured")


def main() -> int:
    args = parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment[OPERATOR_ENV] = "scheduler-operator-integration-secret"
    environment[READER_ENV] = "scheduler-reader-integration-secret"

    allowed_report = args.report.with_name(args.report.stem + "-allowed.json")
    allowed = base_command(
        args, allowed_report, args.report.with_name(args.report.stem + "-allowed.log"))
    allowed.extend((
        "--probe-delay", "0.5",
        "--expect-status", ENDPOINT + "=200",
        "--endpoint-bearer-token-environment", ENDPOINT + "=" + OPERATOR_ENV,
        "--require-body", '"scope":"runtime-process/managed-periodic-tasks"',
        "--require-body", '"id":"pdr.service.workflowRuntime.runDue"',
        "--require-body", '"id":"pdr.service.outboxRuntime.pump"',
        "--require-body", '"mode":"fixed-delay"',
        "--require-body", '"enabled":true',
    ))
    allowed_result = run(allowed, environment)
    body = response_body(allowed_result)
    tasks = body.get("tasks", [])
    if body.get("principal") != "scheduler-operator" or body.get("taskCount") != 2 or \
            not isinstance(tasks, list):
        raise RuntimeError("authenticated scheduler status contract mismatch")
    expected = {
        "pdr.service.workflowRuntime.runDue": "pdr.service.workflowRuntime",
        "pdr.service.outboxRuntime.pump": "pdr.service.outboxRuntime",
    }
    observed: dict[str, dict[str, object]] = {
        str(task.get("id")): task for task in tasks if isinstance(task, dict)
    }
    for task_id, owner in expected.items():
        task = observed.get(task_id)
        if not task or task.get("owner") != owner or task.get("enabled") is not True or \
                task.get("mode") != "fixed-delay" or \
                int(task.get("triggered", 0)) < 1 or int(task.get("accepted", 0)) < 1 or \
                int(task.get("completed", 0)) < 1 or int(task.get("failed", 0)) != 0:
            raise RuntimeError(f"managed periodic task did not execute successfully: {task_id}")

    denied_report = args.report.with_name(args.report.stem + "-denied.json")
    denied = base_command(
        args, denied_report, args.report.with_name(args.report.stem + "-denied.log"))
    denied.extend((
        "--expect-status", ENDPOINT + "=403",
        "--endpoint-bearer-token-environment", ENDPOINT + "=" + READER_ENV,
        "--require-body", "SCHEDULER_PERMISSION_DENIED",
    ))
    denied_result = run(denied, environment)

    anonymous_report = args.report.with_name(args.report.stem + "-anonymous.json")
    anonymous = base_command(
        args, anonymous_report, args.report.with_name(args.report.stem + "-anonymous.log"))
    anonymous.extend((
        "--expect-status", ENDPOINT + "=401",
        "--require-body", "SCHEDULER_AUTHENTICATION_REQUIRED",
    ))
    anonymous_result = run(anonymous, environment)

    for name, result in (("allowed", allowed_result), ("denied", denied_result),
                         ("anonymous", anonymous_result)):
        if not result.get("passed") or not result.get("shutdown", {}).get("clean"):
            raise RuntimeError(f"{name} Runtime did not shut down cleanly")

    summary = {
        "schemaVersion": 1,
        "passed": True,
        "serviceRegistered": True,
        "principal": "scheduler-operator",
        "leastPrivilegeDenied": True,
        "authenticationRequired": True,
        "timerThreads": 1,
        "managedTasks": expected,
        "tasksExecuted": True,
        "shutdownsClean": True,
    }
    args.report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("RUNTIME_SCHEDULER_INTEGRATION_PASS tasks=2 timerThreads=1")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"RUNTIME_SCHEDULER_INTEGRATION_FAIL {error}", file=sys.stderr)
        raise SystemExit(1)
